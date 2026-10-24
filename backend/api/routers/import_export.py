"""Import and export router for watchlistTracker (WT)."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

from portfoliomaster.backup.exporters import export_to_csv, export_to_excel, export_to_json
from portfoliomaster.backup.sqlite_backup import create_automatic_safety_backup
from portfoliomaster.core.models import Exchange, Instrument
from portfoliomaster.db.repository import upsert_instrument
from portfoliomaster.ingest.import_session import import_spreadsheet
from ..common import _instrument_to_dict, get_current_user_id, is_multi_tenant_db
from ..schemas import ImportConfirmRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["import_export"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB limit
MAX_IMPORT_ROWS = 2000              # 2,000 rows limit


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Upload a CSV/Excel file, parse and validate it, returning a preview.
    
    Protects against denial-of-service with a 5 MB file size limit
    and a 2,000 rows ceiling.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xlsx"):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported")

    content_length = file.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum upload size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
        except ValueError:
            pass

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum upload size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        instruments, errors, unresolved, warnings = await asyncio.to_thread(
            import_spreadsheet, tmp_path, file.filename
        )
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

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


@router.post("/import/confirm")
def import_confirm(
    data: ImportConfirmRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Commit previously previewed instruments to the database.
    
    CRITICAL FIX (Bug 5): Persists start_of_year_date and start_of_year_price!
    """
    instruments_payload = [
        item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for item in data.instruments
    ]

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        try:
            with session_scope() as session:
                repo = MultiTenantWatchlistRepository(session, user_id)
                count = repo.import_or_restore_user_watchlist(instruments_payload, replace_all=False)
                session.commit()
            return {"status": "ok", "committed": count, "errors": []}
        except Exception as e:
            logger.exception("Error committing instruments in multi-tenant mode: %s", e)
            raise HTTPException(
                status_code=400,
                detail=f"Database error during import: {e}"
            )

    committed = 0
    commit_errors: list[str] = []

    try:
        create_automatic_safety_backup(reason="pre_import")
    except Exception as e:
        logger.warning(f"Could not create safety backup before import: {e}")

    for inst_dict in instruments_payload:
        try:
            ticker = inst_dict.get("user_ticker", "").strip()
            if not ticker:
                commit_errors.append("Missing user_ticker in instrument data")
                continue

            exchange_val = inst_dict.get("exchange", "UNKNOWN")
            try:
                exchange = Exchange(exchange_val)
            except ValueError:
                exchange = Exchange.UNKNOWN

            ref_price = inst_dict.get("analysis_reference_price")
            tgt_price = inst_dict.get("target_price")
            soy_price = inst_dict.get("start_of_year_price")

            ref_dec = Decimal(str(ref_price)) if ref_price is not None and float(ref_price) > 0 else None
            tgt_dec = Decimal(str(tgt_price)) if tgt_price is not None and float(tgt_price) > 0 else None
            soy_dec = Decimal(str(soy_price)) if soy_price is not None and float(soy_price) > 0 else None

            analysis_dt = None
            if inst_dict.get("analysis_date"):
                try:
                    analysis_dt = date.fromisoformat(str(inst_dict["analysis_date"]))
                except ValueError:
                    pass
            if ref_dec is not None and analysis_dt is None:
                analysis_dt = date.today()

            soy_dt = None
            if inst_dict.get("start_of_year_date"):
                try:
                    soy_dt = date.fromisoformat(str(inst_dict["start_of_year_date"]))
                except ValueError:
                    pass
            if soy_dec is not None and soy_dt is None:
                soy_dt = date(date.today().year, 1, 1)

            # Active boolean parsing
            raw_active = inst_dict.get("active", True)
            if isinstance(raw_active, str):
                is_active = raw_active.strip().lower() not in ("false", "0", "no", "f", "")
            else:
                is_active = bool(raw_active)

            inst = Instrument(
                user_ticker=ticker,
                provider_symbol=inst_dict.get("provider_symbol"),
                exchange=exchange,
                currency=inst_dict.get("currency", ""),
                company_name=inst_dict.get("company_name", ticker),
                analysis_date=analysis_dt,
                analysis_reference_price=ref_dec,
                start_of_year_date=soy_dt,
                start_of_year_price=soy_dec,
                target_price=tgt_dec,
                comment=inst_dict.get("comment", ""),
                active=is_active,
            )
            upsert_instrument(inst)
            committed += 1
        except Exception as e:
            commit_errors.append(f"Error importing '{inst_dict.get('user_ticker', '?')}': {e}")

    return {"status": "ok", "committed": committed, "errors": commit_errors}


@router.get("/export/csv")
def export_csv(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Export the complete watchlist to CSV format with formula injection protection."""
    records = None
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            records = repo.get_positions_with_calculations(active_only=False)

    csv_content = export_to_csv(records=records)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfoliomaster_export_{today_str}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/excel")
def export_excel(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Export the complete watchlist to Excel (.xlsx) format with formula injection protection."""
    records = None
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            records = repo.get_positions_with_calculations(active_only=False)

    excel_bytes = export_to_excel(records=records)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfoliomaster_export_{today_str}.xlsx"
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/json")
def export_json(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Export the complete watchlist to versioned JSON schema snapshot."""
    records = None
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            records = repo.get_positions_with_calculations(active_only=False)

    json_str = export_to_json(records=records)
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfoliomaster_backup_{today_str}.json"
    return Response(
        content=json_str,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
