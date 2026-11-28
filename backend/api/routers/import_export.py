"""Import and export router for watchlistTracker (WT)."""

from __future__ import annotations

import asyncio
import io
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

from portfoliomaster.backup.sqlite_backup import create_automatic_safety_backup
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.db.repository import upsert_instrument

from ..common import get_current_user_id
from ..dependencies import get_portfolio_store
from ..schemas import ImportConfirmRequest
from ..services import import_export_service

_ORIG_UPSERT_INSTRUMENT = upsert_instrument

router = APIRouter(prefix="/api", tags=["import_export"])

MAX_UPLOAD_BYTES = import_export_service.MAX_UPLOAD_BYTES
MAX_IMPORT_ROWS = import_export_service.MAX_IMPORT_ROWS


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Upload a CSV/Excel file, parse and validate it, returning a size- and row-bounded preview."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xlsx"):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported")

    content = await import_export_service.read_limited_upload(file, MAX_UPLOAD_BYTES)
    instruments, errors, unresolved, warnings = await asyncio.to_thread(
        import_export_service.parse_import_bytes,
        content,
        ext,
        file.filename,
        MAX_IMPORT_ROWS,
    )
    return import_export_service.format_import_preview(instruments, errors, unresolved, warnings)


@router.post("/import/confirm")
def import_confirm(
    data: ImportConfirmRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Commit previously previewed instruments to the database."""
    custom_upsert = upsert_instrument if upsert_instrument is not _ORIG_UPSERT_INSTRUMENT else None
    return import_export_service.confirm_import(
        data,
        user_id,
        store,
        backup_fn=create_automatic_safety_backup,
        sqlite_upsert_fn=custom_upsert,
    )


@router.get("/export/csv")
def export_csv(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Export the complete watchlist to CSV format with formula injection protection."""
    payload, media_type, filename = import_export_service.export_watchlist_payload(store, "csv")
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/excel")
def export_excel(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Export the complete watchlist to Excel (.xlsx) format with formula injection protection."""
    payload, media_type, filename = import_export_service.export_watchlist_payload(store, "excel")
    return StreamingResponse(
        io.BytesIO(payload if isinstance(payload, bytes) else payload.encode("utf-8")),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/json")
def export_json(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Export the complete watchlist to versioned JSON schema snapshot."""
    payload, media_type, filename = import_export_service.export_watchlist_payload(store, "json")
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
