"""Domain service for CSV/Excel import parsing, transactional confirmation, and exports."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import HTTPException, UploadFile

from portfoliomaster.backup.exporters import export_to_csv, export_to_excel, export_to_json
from portfoliomaster.backup.sqlite_backup import create_automatic_safety_backup
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.ingest.import_session import import_spreadsheet

from ..common import _instrument_to_dict, is_production
from ..schemas import ImportConfirmRequest
from .cache import invalidate_positions_cache

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB limit
MAX_IMPORT_ROWS = 2000              # 2,000 rows limit


def parse_import_bytes(content: bytes, ext: str, filename: str, max_rows: int):
    """Write uploaded bytes to a temp file, parse synchronously, and clean up off the event loop."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        return import_spreadsheet(tmp_path, filename, max_rows)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def read_limited_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Validate upload filename/content-length and stream bounded bytes safely."""
    content_length = file.headers.get("content-length") if file.headers else None
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum upload size of {max_bytes // (1024 * 1024)} MB.",
                )
        except ValueError:
            pass

    chunks = bytearray()
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        if len(chunks) + len(chunk) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds maximum upload size of {max_bytes // (1024 * 1024)} MB.",
            )
        chunks.extend(chunk)
    return bytes(chunks)


def format_import_preview(
    instruments: list[Any], errors: list[str], unresolved: list[str], warnings: list[str]
) -> dict:
    """Format parsed preview results and enforce row count ceiling."""
    if len(instruments) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"File contains {len(instruments)} rows, which exceeds the maximum limit of {MAX_IMPORT_ROWS} rows.",
        )

    return {
        "instruments": [_instrument_to_dict(inst) for inst in instruments],
        "errors": errors,
        "unresolved": unresolved,
        "warnings": warnings,
        "valid_count": len(instruments),
    }


def confirm_import(
    data: ImportConfirmRequest,
    user_id: uuid.UUID,
    store: PortfolioStore,
    *,
    backup_fn: Callable[..., Any] = create_automatic_safety_backup,
    sqlite_upsert_fn: Optional[Callable[[Any], Any]] = None,
) -> dict:
    """Persist previewed instruments via the unified PortfolioStore port."""
    instruments_payload = [
        item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for item in data.instruments
    ]

    if store.supports_sqlite_file_backups:
        try:
            backup_fn(reason="pre_import")
        except Exception as e:
            logger.warning("Could not create safety backup before import: %s", e)

    commit_errors: list[str] = []
    if sqlite_upsert_fn is not None and store.supports_sqlite_file_backups:
        # Support explicit row-by-row callback when injected
        committed = 0
        from portfoliomaster.db.repository import SqliteWatchlistStore

        for item in instruments_payload:
            ticker = str(item.get("user_ticker") or "").strip()
            if not ticker:
                commit_errors.append("Missing user_ticker in instrument data")
                continue
            try:
                assert isinstance(store, SqliteWatchlistStore)
                committed += store.import_watchlist([item], replace_all=False, upsert_fn=sqlite_upsert_fn)
            except Exception as e:
                logger.warning("Error importing '%s': %s", ticker, e)
                msg = (
                    f"Error importing '{ticker}'"
                    if is_production()
                    else f"Error importing '{ticker}': {e}"
                )
                commit_errors.append(msg)

        invalidate_positions_cache(user_id if not store.supports_sqlite_file_backups else None)
        if committed == 0 and commit_errors:
            raise HTTPException(
                status_code=400,
                detail={"message": "Import failed for all instruments.", "errors": commit_errors},
            )
        return {
            "status": "partial" if commit_errors else "ok",
            "committed": committed,
            "errors": commit_errors,
        }

    for item in instruments_payload:
        if not str(item.get("user_ticker") or "").strip():
            commit_errors.append("Missing user_ticker in instrument data")

    try:
        committed = store.import_watchlist(instruments_payload, replace_all=False)
    except Exception as e:
        logger.exception("Error committing instruments during import: %s", e)
        detail = "Database error during import." if is_production() else f"Database error during import: {e}"
        raise HTTPException(status_code=400, detail=detail) from e

    invalidate_positions_cache(user_id if not store.supports_sqlite_file_backups else None)
    if committed == 0 and commit_errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Import failed for all instruments.", "errors": commit_errors},
        )
    status_label = "partial" if commit_errors else "ok"
    return {"status": status_label, "committed": committed, "errors": commit_errors}


def export_watchlist_payload(store: PortfolioStore, fmt: str) -> tuple[bytes | str, str, str]:
    """Generate CSV, Excel, or JSON export payload, media_type, and suggested filename."""
    records = None if store.supports_sqlite_file_backups else store.export_records()
    today_str = datetime.now().strftime("%Y-%m-%d")

    if fmt == "csv":
        return (
            export_to_csv(records=records),
            "text/csv; charset=utf-8",
            f"portfoliomaster_export_{today_str}.csv",
        )
    if fmt == "excel":
        return (
            export_to_excel(records=records),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"portfoliomaster_export_{today_str}.xlsx",
        )
    if fmt == "json":
        return (
            export_to_json(records=records),
            "application/json; charset=utf-8",
            f"portfoliomaster_backup_{today_str}.json",
        )
    raise ValueError(f"Unsupported export format: {fmt}")
