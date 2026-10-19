"""SQLite snapshot, automatic safety backups, validation and restoration."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional, Tuple

from ..db.connection import DB_PATH, PROJECT_ROOT


def get_backup_dir() -> str:
    """Return the absolute path to the backups directory, creating it if needed."""
    backup_dir = os.environ.get("PORTFOLIOMASTER_BACKUP_DIR") or os.path.join(PROJECT_ROOT, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    return os.path.abspath(backup_dir)


def get_target_db_path(source_db_path: Optional[str] = None) -> str:
    """Resolve the active SQLite database path."""
    return source_db_path or os.environ.get("PORTFOLIOMASTER_DB_PATH") or DB_PATH


def create_sqlite_backup(
    target_path: Optional[str] = None,
    source_db_path: Optional[str] = None,
) -> str:
    """
    Create an atomic, thread-safe snapshot of the active SQLite database
    using sqlite3.Connection.backup().
    """
    src_path = get_target_db_path(source_db_path)
    if target_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = os.path.join(get_backup_dir(), f"portfolio_backup_{timestamp}.db")

    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

    # If the source DB file doesn't exist yet, create an empty one first
    if not os.path.exists(src_path):
        conn = sqlite3.connect(src_path)
        conn.close()

    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(target_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    return os.path.abspath(target_path)


def rotate_backups(backup_dir: Optional[str] = None, keep: int = 10) -> None:
    """Keep only the latest `keep` backups in the backup directory."""
    b_dir = backup_dir or get_backup_dir()
    if not os.path.exists(b_dir):
        return

    entries = []
    for fname in os.listdir(b_dir):
        if fname.endswith(".db"):
            fpath = os.path.join(b_dir, fname)
            if os.path.isfile(fpath):
                entries.append((os.path.getmtime(fpath), fpath))

    # Sort descending by modification time (newest first)
    entries.sort(key=lambda x: x[0], reverse=True)

    # Delete older than `keep`
    for _, fpath in entries[keep:]:
        try:
            os.remove(fpath)
        except OSError:
            pass


def create_automatic_safety_backup(
    source_db_path: Optional[str] = None,
    reason: str = "safety",
) -> Optional[str]:
    """
    Create an automatic timestamped backup in the backups/ directory
    and enforce a rotation of the latest 10 automatic backups.
    """
    src_path = get_target_db_path(source_db_path)
    if not os.path.exists(src_path) or os.path.getsize(src_path) == 0:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_reason = "".join(c for c in reason if c.isalnum() or c in ("_", "-"))
    filename = f"portfolio_backup_{timestamp}_{sanitized_reason}.db"
    dest_path = os.path.join(get_backup_dir(), filename)

    created_path = create_sqlite_backup(target_path=dest_path, source_db_path=src_path)
    rotate_backups(get_backup_dir(), keep=10)
    return created_path


def validate_sqlite_backup(db_path: str) -> Tuple[bool, Optional[str]]:
    """
    Verify SQLite integrity (PRAGMA integrity_check) and schema requirements
    (instruments table with user_ticker column).
    """
    if not os.path.exists(db_path):
        return False, f"El archivo no existe: {db_path}"

    if os.path.getsize(db_path) == 0:
        return False, "El archivo de copia de seguridad está vacío."

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. PRAGMA integrity_check
        cursor.execute("PRAGMA integrity_check")
        rows = cursor.fetchall()
        if not rows or rows[0][0] != "ok":
            detail = "; ".join(r[0] for r in rows) if rows else "desconocido"
            conn.close()
            return False, f"Fallo de integridad SQLite: {detail}"

        # 2. Check required tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cursor.fetchall()}
        if "instruments" not in tables:
            conn.close()
            return False, "La base de datos no contiene la tabla obligatoria 'instruments'."

        # 3. Check required columns in instruments
        cursor.execute("PRAGMA table_info(instruments)")
        columns = {r[1] for r in cursor.fetchall()}
        if "user_ticker" not in columns:
            conn.close()
            return False, "La tabla 'instruments' no contiene la columna obligatoria 'user_ticker'."

        conn.close()
        return True, None
    except Exception as e:
        return False, f"Error validando el archivo SQLite: {e}"


def restore_sqlite_backup(
    backup_path: str,
    target_db_path: Optional[str] = None,
    create_safety_backup: bool = True,
) -> dict:
    """
    Restore database from a validated SQLite snapshot.
    Triggers an automatic safety backup of current DB before replacing.
    """
    is_valid, error_msg = validate_sqlite_backup(backup_path)
    if not is_valid:
        raise ValueError(error_msg or "Copia de seguridad SQLite no válida")

    tgt_path = get_target_db_path(target_db_path)

    # Safety backup of active database before overwrite
    if create_safety_backup and os.path.exists(tgt_path) and os.path.getsize(tgt_path) > 0:
        create_automatic_safety_backup(tgt_path, reason="pre_restore")

    # Perform atomic restore using SQLite backup API
    src_conn = sqlite3.connect(backup_path)
    dst_conn = sqlite3.connect(tgt_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    # Query summary of restored instruments
    conn = sqlite3.connect(tgt_path)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM instruments WHERE active = 1")
    count_active = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM instruments")
    count_total = cursor.fetchone()[0]
    cursor.execute("SELECT user_ticker FROM instruments LIMIT 10")
    sample_tickers = [r[0] for r in cursor.fetchall()]
    conn.close()

    return {
        "status": "ok",
        "restored_instruments": count_total,
        "active_instruments": count_active,
        "sample_tickers": sample_tickers,
        "backup_filename": os.path.basename(backup_path),
    }


def list_automatic_backups(backup_dir: Optional[str] = None) -> list[dict]:
    """List available local automatic backups in backups/ ordered by date descending."""
    b_dir = backup_dir or get_backup_dir()
    if not os.path.exists(b_dir):
        return []

    backups = []
    for fname in os.listdir(b_dir):
        if fname.endswith(".db"):
            fpath = os.path.join(b_dir, fname)
            if os.path.isfile(fpath):
                try:
                    stat = os.stat(fpath)
                    created_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    backups.append({
                        "filename": fname,
                        "size_bytes": stat.st_size,
                        "created_at": created_at,
                        "type": "db",
                    })
                except OSError:
                    continue

    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


def restore_automatic_backup(
    filename: str,
    backup_dir: Optional[str] = None,
    target_db_path: Optional[str] = None,
) -> dict:
    """Restore from a specific local backup file in backups/."""
    # Defend against path traversal
    base_name = os.path.basename(filename)
    if base_name != filename or not filename.endswith(".db"):
        raise ValueError("Nombre de archivo de copia de seguridad no válido.")

    b_dir = backup_dir or get_backup_dir()
    file_path = os.path.join(b_dir, filename)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"No se encontró la copia de seguridad: {filename}")

    return restore_sqlite_backup(file_path, target_db_path=target_db_path)
