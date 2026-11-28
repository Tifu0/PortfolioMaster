"""Domain service for database wipe, snapshot backup downloads, and restore."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from decimal import InvalidOperation
from typing import Any, Callable

from fastapi import HTTPException, Response, UploadFile

from portfoliomaster.backup.exporters import (
    export_to_json,
    restore_from_json as _default_restore_from_json,
    validate_json_backup_payload,
)
from portfoliomaster.backup.sqlite_backup import (
    create_automatic_safety_backup,
    create_sqlite_backup,
    list_automatic_backups,
    restore_automatic_backup,
    restore_sqlite_backup,
    validate_sqlite_backup,
)
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.db.session import is_production

from .cache import invalidate_positions_cache

logger = logging.getLogger(__name__)

MAX_BACKUP_BYTES = 10 * 1024 * 1024  # 10 MB limit


def wipe_database_for_store(store: PortfolioStore, user_id: uuid.UUID) -> dict:
    """Wipe all tenant or local instruments safely and invalidate caches."""
    if store.supports_sqlite_file_backups:
        try:
            create_automatic_safety_backup(reason="pre_wipe")
        except Exception as e:
            logger.warning("Could not create safety backup before wipe: %s", e)

    store.wipe_all()
    if store.supports_sqlite_file_backups:
        invalidate_positions_cache()
        return {"status": "ok", "detail": "Database wiped successfully"}

    invalidate_positions_cache(user_id)
    return {"status": "ok", "detail": "Tenant instruments wiped successfully"}


def download_backup_response(store: PortfolioStore) -> Response:
    """Return a versioned JSON snapshot (multi-tenant) or SQLite .db file download."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    if not store.supports_sqlite_file_backups:
        records = store.export_records()
        json_str = export_to_json(records=records)
        filename = f"portfoliomaster_backup_{today_str}.json"
        return Response(
            content=json_str,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    filename = f"portfoliomaster_backup_{today_str}.db"
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        create_sqlite_backup(target_path=tmp_path)
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return Response(
        content=data,
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def restore_backup_upload(
    file: UploadFile,
    user_id: uuid.UUID,
    store: PortfolioStore,
    *,
    restore_json_fn: Callable[[dict], dict] = _default_restore_from_json,
) -> dict:
    """Validate and atomically restore a .json or .db backup upload."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    contents = file.file.read(MAX_BACKUP_BYTES + 1)
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if len(contents) > MAX_BACKUP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum upload size of {MAX_BACKUP_BYTES // (1024 * 1024)} MB.",
        )

    lower_name = file.filename.lower()

    if lower_name.endswith(".json"):
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid file encoding: backup file must be UTF-8 encoded text.",
            ) from exc

        try:
            payload = json.loads(text)
        except Exception as e:
            logger.warning("[BackupRestore] Invalid JSON payload: %s", e)
            detail = "Invalid JSON format." if is_production() else f"Invalid JSON format: {e}"
            raise HTTPException(status_code=400, detail=detail) from e

        try:
            validated_items = validate_json_backup_payload(payload)
        except (ValueError, InvalidOperation) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        if not store.supports_sqlite_file_backups:
            try:
                restored_count = store.import_watchlist(validated_items, replace_all=True)
                invalidate_positions_cache(user_id)
                return {
                    "status": "ok",
                    "restored_count": restored_count,
                    "instruments": restored_count,
                    "quotes": 0,
                    "detail": f"Restored {restored_count} instruments successfully",
                }
            except Exception as e:
                logger.error("[BackupRestore] Multi-tenant restore failed: %s", e)
                raise HTTPException(
                    status_code=500,
                    detail="Database restore failed. All changes have been rolled back.",
                ) from e

        try:
            result = restore_json_fn(payload)
            invalidate_positions_cache()
            return result
        except (ValueError, InvalidOperation) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.error("[BackupRestore] SQLite restore failed: %s", e)
            raise HTTPException(
                status_code=500,
                detail="Database restore failed. All changes have been rolled back.",
            ) from e

    if lower_name.endswith((".db", ".sqlite", ".sqlite3")):
        if not store.supports_sqlite_file_backups:
            raise HTTPException(
                status_code=400,
                detail="Raw SQLite .db upload is disabled in PostgreSQL multi-tenant mode. Please upload a .json backup file.",
            )

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(contents)
            is_valid, err = validate_sqlite_backup(tmp_path)
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=err or "Invalid or corrupted SQLite file",
                )
            result = restore_sqlite_backup(tmp_path)
            invalidate_positions_cache()
            return result
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.error("[BackupRestore] SQLite restore failed: %s", e)
            raise HTTPException(status_code=500, detail="Database restore failed.") from e
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    raise HTTPException(
        status_code=400,
        detail="Unsupported file format. Please upload a .db (SQLite) or .json backup.",
    )


def list_backups_for_store(store: PortfolioStore) -> dict:
    """List local automatic SQLite backups when supported by the store."""
    if not store.supports_sqlite_file_backups:
        return {
            "status": "ok",
            "backups": [],
            "count": 0,
            "note": "Local filesystem backups are disabled in PostgreSQL multi-tenant mode. Use JSON backup exports.",
        }
    backups = list_automatic_backups()
    return {"status": "ok", "backups": backups, "count": len(backups)}


def restore_local_backup_for_store(filename: str, store: PortfolioStore) -> dict:
    """Restore an automatic local SQLite backup when supported by the store."""
    if not store.supports_sqlite_file_backups:
        raise HTTPException(
            status_code=400,
            detail="Local filesystem restore is disabled in PostgreSQL multi-tenant mode. Please use /api/backup/restore with a JSON backup.",
        )
    try:
        result = restore_automatic_backup(filename)
        invalidate_positions_cache()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("[BackupRestore] Local automatic backup restore failed: %s", e)
        detail = "Error restoring backup." if is_production() else f"Error restoring backup: {e}"
        raise HTTPException(status_code=500, detail=detail) from e
