"""Database backup, snapshot, and restore router for watchlistTracker (WT)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from portfoliomaster.backup.exporters import (
    export_to_json,
    restore_from_json,
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
from portfoliomaster.db.repository import wipe_database
from ..common import get_current_user_id, is_multi_tenant_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["backup"])

MAX_BACKUP_BYTES = 10 * 1024 * 1024  # 10 MB limit


@router.delete("/database")
def wipe_db(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Wipe all data from the database (instruments + quotes for this tenant)."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.schema import UserInstrument
        from sqlalchemy import delete

        with session_scope() as session:
            session.execute(delete(UserInstrument).where(UserInstrument.user_id == user_id))
            session.commit()
        return {"status": "ok", "detail": "Tenant instruments wiped successfully"}

    try:
        create_automatic_safety_backup(reason="pre_wipe")
    except Exception as e:
        logger.warning(f"Could not create safety backup before wipe: {e}")
    wipe_database()
    return {"status": "ok", "detail": "Database wiped successfully"}


@router.get("/backup/download")
def download_backup(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Download backup: versioned JSON snapshot for multi-tenant, or SQLite .db for local SQLite."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            records = repo.get_positions_with_calculations(active_only=False)

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


@router.post("/backup/restore")
async def restore_backup(
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Accept an uploaded backup file (.json or .db), validate it,
    restore data atomically for this tenant, and return a summary of restored instruments.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if len(contents) > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds maximum upload size of {MAX_BACKUP_BYTES // (1024*1024)} MB.")

    lower_name = file.filename.lower()

    if lower_name.endswith(".json"):
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Invalid file encoding: backup file must be UTF-8 encoded text.")

        try:
            payload = json.loads(text)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

        # Strict schema & data validation before touching database
        try:
            validated_items = validate_json_backup_payload(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if is_multi_tenant_db():
            from portfoliomaster.db.session import session_scope
            from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

            try:
                with session_scope() as session:
                    repo = MultiTenantWatchlistRepository(session, user_id)
                    restored_count = repo.import_or_restore_user_watchlist(validated_items, replace_all=True)
                return {
                    "status": "ok",
                    "restored_count": restored_count,
                    "instruments": restored_count,
                    "quotes": 0,
                    "detail": f"Restored {restored_count} instruments successfully",
                }
            except Exception as e:
                logger.error("[BackupRestore] Multi-tenant restore failed: %s", e)
                raise HTTPException(status_code=500, detail="Database restore failed. All changes have been rolled back.")

        try:
            result = restore_from_json(payload)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error("[BackupRestore] SQLite restore failed: %s", e)
            raise HTTPException(status_code=500, detail="Database restore failed. All changes have been rolled back.")

    elif lower_name.endswith((".db", ".sqlite", ".sqlite3")):
        if is_multi_tenant_db():
            raise HTTPException(
                status_code=400,
                detail="Raw SQLite .db upload is disabled in PostgreSQL multi-tenant mode. Please upload a .json backup file.",
            )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        try:
            is_valid, err = validate_sqlite_backup(tmp_path)
            if not is_valid:
                raise HTTPException(status_code=400, detail=err or "Invalid or corrupted SQLite file")
            result = restore_sqlite_backup(tmp_path)
            return result
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error restoring database: {e}")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a .db (SQLite) or .json backup.",
        )


@router.get("/backup/list")
def list_backups(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """List available local automatic backups (local development only)."""
    if is_multi_tenant_db():
        return {
            "status": "ok",
            "backups": [],
            "count": 0,
            "note": "Local filesystem backups are disabled in PostgreSQL multi-tenant mode. Use JSON backup exports.",
        }
    backups = list_automatic_backups()
    return {"status": "ok", "backups": backups, "count": len(backups)}


@router.post("/backup/restore/{filename}")
def restore_local_backup_endpoint(
    filename: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Restore database from a local automatic backup file (local development only)."""
    if is_multi_tenant_db():
        raise HTTPException(
            status_code=400,
            detail="Local filesystem restore is disabled in PostgreSQL multi-tenant mode. Please use /api/backup/restore with a JSON backup.",
        )
    try:
        result = restore_automatic_backup(filename)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error restoring backup: {e}")
