"""Database backup, snapshot, and restore router for watchlistTracker (WT)."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, File, UploadFile

from portfoliomaster.backup.exporters import restore_from_json
from portfoliomaster.db.ports import PortfolioStore

from ..common import get_current_user_id
from ..dependencies import get_portfolio_store
from ..services import backup_service

router = APIRouter(prefix="/api", tags=["backup"])


@router.delete("/database")
def wipe_db(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Wipe all data from the database (instruments + quotes for this tenant)."""
    return backup_service.wipe_database_for_store(store, user_id)


@router.get("/backup/download")
def download_backup(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Download backup: versioned JSON snapshot for multi-tenant, or SQLite .db for local SQLite."""
    return backup_service.download_backup_response(store)


@router.post("/backup/restore")
def restore_backup(
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Accept an uploaded backup file (.json or .db), validate and restore atomically."""
    return backup_service.restore_backup_upload(
        file,
        user_id,
        store,
        restore_json_fn=restore_from_json,
    )


@router.get("/backup/list")
def list_backups(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """List available local automatic backups (local development only)."""
    return backup_service.list_backups_for_store(store)


@router.post("/backup/restore/{filename}")
def restore_local_backup_endpoint(
    filename: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Restore database from a local automatic backup file (local development only)."""
    return backup_service.restore_local_backup_for_store(filename, store)
