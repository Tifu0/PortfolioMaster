"""Watchlist data exporters (CSV, Excel .xlsx, JSON) and JSON restore logic."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..core.calculations import (
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)
from ..core.models import Exchange, Instrument, Quote, QuoteStatus
from ..db.connection import get_connection
from ..db.repository import (
    get_all_instruments,
    get_quote_by_instrument_id,
    upsert_instrument,
    upsert_quote,
    wipe_database,
)
from .sqlite_backup import create_automatic_safety_backup, get_target_db_path


def _serialize_date(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    return str(val)


def _serialize_decimal(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return None


def get_export_records(db_path: Optional[str] = None) -> List[dict]:
    """
    Retrieve all instruments with latest quotes and server-computed variations.
    """
    conn = get_connection(db_path)
    # Ensure tables exist
    conn.row_factory = None
    instruments = get_all_instruments()
    conn.close()

    records = []
    for inst in instruments:
        quote = get_quote_by_instrument_id(inst.id) if inst.id else None

        # Calculate derived metrics
        daily_res = daily_variation(quote.price, quote.previous_close) if quote else None
        analysis_res = (
            variation_since_analysis(quote.price, inst.analysis_reference_price)
            if quote
            else None
        )
        ytd_res = ytd_variation(quote.price, inst.start_of_year_price) if quote else None
        target_res = decline_to_target(quote.price, inst.target_price) if quote else None

        exchange_str = inst.exchange.value if isinstance(inst.exchange, Exchange) else str(inst.exchange or "US")
        status_str = quote.status.name if quote and hasattr(quote.status, "name") else (str(quote.status) if quote else "UNAVAILABLE")

        records.append({
            # Ingest-compatible columns
            "user_ticker": inst.user_ticker,
            "company_name": inst.company_name or inst.user_ticker,
            "currency": inst.currency or "USD",
            "analysis_reference_price": _serialize_decimal(inst.analysis_reference_price),
            "analysis_date": _serialize_date(inst.analysis_date),
            "start_of_year_price": _serialize_decimal(inst.start_of_year_price),
            "start_of_year_date": _serialize_date(inst.start_of_year_date),
            "target_price": _serialize_decimal(inst.target_price),
            "comment": inst.comment or "",
            "active": inst.active,
            # Quote & Market values
            "latest_price": _serialize_decimal(quote.price) if quote else None,
            "previous_close": _serialize_decimal(quote.previous_close) if quote else None,
            "daily_variation": _serialize_decimal(daily_res.daily_variation) if daily_res and daily_res.daily_variation_valid else None,
            "ytd_variation": _serialize_decimal(ytd_res.ytd_variation) if ytd_res and ytd_res.ytd_variation_valid else None,
            "variation_since_analysis": _serialize_decimal(analysis_res.variation_since_analysis) if analysis_res and analysis_res.variation_since_analysis_valid else None,
            "decline_to_target": _serialize_decimal(target_res.decline_to_target) if target_res and target_res.decline_to_target_valid else None,
            "exchange": exchange_str,
            "provider_symbol": inst.provider_symbol or inst.user_ticker,
            "quote_timestamp": _serialize_date(quote.quote_timestamp) if quote and quote.quote_timestamp else None,
            "quote_status": status_str,
            # Raw quote for JSON full dump
            "_quote": {
                "price": _serialize_decimal(quote.price) if quote else None,
                "previous_close": _serialize_decimal(quote.previous_close) if quote else None,
                "quote_timestamp": quote.quote_timestamp.isoformat() if quote and quote.quote_timestamp else None,
                "fetched_at": quote.fetched_at.isoformat() if quote and quote.fetched_at else None,
                "provider": quote.provider if quote else "",
                "status": status_str,
                "error_message": quote.error_message if quote else None,
            } if quote else None,
        })

    return records


# Header definitions designed for 100% round-trip ingest compatibility:
# The first columns map directly to COLUMN_MAPPING in src/portfoliomaster/ingest/columns.py
EXPORT_COLUMNS = [
    ("Ticker", "user_ticker"),
    ("Empresa", "company_name"),
    ("Divisa", "currency"),
    ("Precio de Análisis", "analysis_reference_price"),
    ("Fecha de Análisis", "analysis_date"),
    ("Precio Inicio Año", "start_of_year_price"),
    ("Fecha Inicio Año", "start_of_year_date"),
    ("Precio Objetivo", "target_price"),
    ("Notas", "comment"),
    ("Active", "active"),
    # Derived / informative columns (ignored by column mapper on import)
    ("Último Precio", "latest_price"),
    ("Cierre Anterior", "previous_close"),
    ("Var. Diaria %", "daily_variation"),
    ("Var. YTD %", "ytd_variation"),
    ("Var. vs Análisis %", "variation_since_analysis"),
    ("Caída a Objetivo %", "decline_to_target"),
    ("Mercado", "exchange"),
    ("Símbolo Proveedor", "provider_symbol"),
    ("Fecha Cotización", "quote_timestamp"),
    ("Estado Cotización", "quote_status"),
]


def export_to_csv(records: Optional[List[dict]] = None, db_path: Optional[str] = None) -> str:
    """
    Export watchlist to CSV string with UTF-8 encoding.
    Headers are 100% compatible with the ingest parser.
    """
    if records is None:
        records = get_export_records(db_path)

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Header row
    headers = [col[0] for col in EXPORT_COLUMNS]
    writer.writerow(headers)

    # Data rows
    for r in records:
        row = []
        for _, key in EXPORT_COLUMNS:
            val = r.get(key)
            if val is None:
                row.append("")
            elif isinstance(val, bool):
                row.append("1" if val else "0")
            elif isinstance(val, float):
                # Standard dot decimal format
                row.append(f"{val:.2f}" if abs(val) >= 0.01 else f"{val:.4f}")
            else:
                row.append(str(val))
        writer.writerow(row)

    return output.getvalue()


def export_to_excel(records: Optional[List[dict]] = None, db_path: Optional[str] = None) -> bytes:
    """
    Export watchlist to .xlsx workbook with clean styling and auto-sized columns.
    Headers are 100% compatible with the ingest parser.
    """
    if records is None:
        records = get_export_records(db_path)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Watchlist"

    # Styling constants
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")  # Slate 900
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    border_thin = Side(border_style="thin", color="E2E8F0")
    cell_border = Border(left=border_thin, right=border_thin, top=border_thin, bottom=border_thin)

    # Write Header
    headers = [col[0] for col in EXPORT_COLUMNS]
    ws.append(headers)

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Write Data
    for row_idx, r in enumerate(records, start=2):
        row_values = []
        for _, key in EXPORT_COLUMNS:
            val = r.get(key)
            if val is None:
                row_values.append("")
            elif isinstance(val, bool):
                row_values.append("Sí" if val else "No")
            elif isinstance(val, (int, float)):
                row_values.append(round(val, 4))
            else:
                row_values.append(str(val))
        ws.append(row_values)

        # Style data row
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=row_idx, column=col_idx)
            c.font = data_font
            c.border = cell_border
            # Align numbers right, text left, short codes center
            if col_idx in (1, 3, 10, 17, 20):  # Ticker, Currency, Active, Market, Status
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in (4, 6, 8, 11, 12, 13, 14, 15, 16):  # Numerical metrics
                c.alignment = Alignment(horizontal="right", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

    # Auto-fit column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Freeze header row
    ws.freeze_panes = "A2"

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_to_json(records: Optional[List[dict]] = None, db_path: Optional[str] = None) -> str:
    """
    Export watchlist to a versioned JSON schema dump.
    """
    if records is None:
        records = get_export_records(db_path)

    dump_instruments = []
    for r in records:
        inst_item = {
            "user_ticker": r["user_ticker"],
            "provider_symbol": r["provider_symbol"],
            "exchange": r["exchange"],
            "currency": r["currency"],
            "company_name": r["company_name"],
            "analysis_date": r["analysis_date"],
            "analysis_reference_price": r["analysis_reference_price"],
            "start_of_year_date": r["start_of_year_date"],
            "start_of_year_price": r["start_of_year_price"],
            "target_price": r["target_price"],
            "comment": r["comment"],
            "active": r["active"],
        }
        if r.get("_quote"):
            inst_item["quote"] = r["_quote"]
        dump_instruments.append(inst_item)

    payload = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "total_positions": len(dump_instruments),
        "instruments": dump_instruments,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def restore_from_json(
    json_data: str | dict,
    target_db_path: Optional[str] = None,
    create_safety_backup: bool = True,
) -> dict:
    """
    Restore instruments and quotes from a validated JSON backup.
    Creates an automatic safety backup of current database first.
    """
    if isinstance(json_data, str):
        try:
            data = json.loads(json_data)
        except Exception as e:
            raise ValueError(f"Formato JSON no válido: {e}")
    else:
        data = json_data

    if not isinstance(data, dict) or "instruments" not in data or not isinstance(data["instruments"], list):
        raise ValueError("El archivo JSON debe contener un objeto con la propiedad 'instruments'.")

    instruments_data = data["instruments"]

    # Validate before making any destructive changes
    for idx, item in enumerate(instruments_data):
        if not isinstance(item, dict) or not str(item.get("user_ticker", "")).strip():
            raise ValueError(f"Fila {idx + 1}: Instrumento no válido, falta 'user_ticker'.")

    tgt_path = get_target_db_path(target_db_path)

    # 1. Automatic safety backup of existing DB
    if create_safety_backup:
        create_automatic_safety_backup(tgt_path, reason="pre_json_restore")

    # 2. Clear current DB
    wipe_database()

    restored_count = 0
    restored_tickers = []

    for item in instruments_data:
        ticker = str(item.get("user_ticker", "")).strip()
        exchange_str = item.get("exchange", "UNKNOWN")
        try:
            exchange = Exchange(exchange_str)
        except ValueError:
            exchange = Exchange.UNKNOWN

        analysis_dt = None
        if item.get("analysis_date"):
            try:
                analysis_dt = date.fromisoformat(str(item["analysis_date"]))
            except ValueError:
                pass

        soy_dt = None
        if item.get("start_of_year_date"):
            try:
                soy_dt = date.fromisoformat(str(item["start_of_year_date"]))
            except ValueError:
                pass

        inst = Instrument(
            user_ticker=ticker,
            provider_symbol=item.get("provider_symbol"),
            exchange=exchange,
            currency=item.get("currency", "USD"),
            company_name=item.get("company_name", ticker),
            analysis_date=analysis_dt,
            analysis_reference_price=Decimal(str(item["analysis_reference_price"])) if item.get("analysis_reference_price") is not None else None,
            start_of_year_date=soy_dt,
            start_of_year_price=Decimal(str(item["start_of_year_price"])) if item.get("start_of_year_price") is not None else None,
            target_price=Decimal(str(item["target_price"])) if item.get("target_price") is not None else None,
            comment=item.get("comment", "") or "",
            active=bool(item.get("active", True)),
        )
        upsert_instrument(inst)

        # Retrieve newly assigned instrument id
        from ..db.repository import get_instrument_by_ticker
        persisted = get_instrument_by_ticker(ticker)

        if persisted and persisted.id and item.get("quote"):
            q_data = item["quote"]
            status_name = q_data.get("status", "UNAVAILABLE")
            try:
                status_enum = QuoteStatus[status_name]
            except (KeyError, ValueError):
                status_enum = QuoteStatus.UNAVAILABLE

            q_ts = None
            if q_data.get("quote_timestamp"):
                try:
                    q_ts = datetime.fromisoformat(str(q_data["quote_timestamp"]))
                except ValueError:
                    pass

            q_fetched = None
            if q_data.get("fetched_at"):
                try:
                    q_fetched = datetime.fromisoformat(str(q_data["fetched_at"]))
                except ValueError:
                    pass

            quote = Quote(
                instrument_id=persisted.id,
                price=Decimal(str(q_data["price"])) if q_data.get("price") is not None else None,
                previous_close=Decimal(str(q_data["previous_close"])) if q_data.get("previous_close") is not None else None,
                quote_timestamp=q_ts,
                fetched_at=q_fetched,
                provider=q_data.get("provider", ""),
                status=status_enum,
                error_message=q_data.get("error_message"),
            )
            upsert_quote(quote)

        restored_count += 1
        restored_tickers.append(ticker)

    return {
        "status": "ok",
        "restored_instruments": restored_count,
        "sample_tickers": restored_tickers[:10],
        "type": "json",
    }
