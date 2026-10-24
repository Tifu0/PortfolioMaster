"""Watchlist data exporters (CSV, Excel .xlsx, JSON) and JSON restore logic for watchlistTracker (WT)."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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


def _sanitize_formula(val: Any) -> Any:
    """Protect spreadsheet users against Formula Injection (CSV/Excel macro injection)."""
    if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@"):
        return f"'{val}"
    return val


def get_export_records(db_path: Optional[str] = None) -> List[dict]:
    """
    Retrieve all instruments with latest quotes and server-computed variations.
    Scoped explicitly to db_path when provided.
    """
    instruments = get_all_instruments(include_inactive=False, db_path=db_path)

    records = []
    for inst in instruments:
        quote = get_quote_by_instrument_id(inst.id, db_path=db_path) if inst.id else None

        # Calculate derived metrics
        daily_res = daily_variation(quote.price, quote.previous_close) if quote else None
        analysis_res = (
            variation_since_analysis(quote.price, inst.analysis_reference_price)
            if quote
            else None
        )
        ytd_res = ytd_variation(quote.price, inst.start_of_year_price) if quote else None
        
        # CRITICAL FIX (Bug 4): decline_to_target signature is (target_price, latest_price)
        target_res = decline_to_target(inst.target_price, quote.price) if quote else None

        exchange_str = inst.exchange.value if isinstance(inst.exchange, Exchange) else str(inst.exchange or "US")
        status_str = quote.status.name if quote and hasattr(quote.status, "name") else (str(quote.status) if quote else "UNAVAILABLE")

        records.append({
            # Ingest-compatible columns (English)
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
            "quote_timestamp": quote.quote_timestamp.isoformat() if quote and quote.quote_timestamp else None,
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


# Header definitions in English for WatchlistTracker (WT), 100% round-trip ingest compatible
EXPORT_COLUMNS = [
    ("Ticker", "user_ticker"),
    ("Company", "company_name"),
    ("Currency", "currency"),
    ("Analysis Price", "analysis_reference_price"),
    ("Analysis Date", "analysis_date"),
    ("Start of Year Price", "start_of_year_price"),
    ("Start of Year Date", "start_of_year_date"),
    ("Target Price", "target_price"),
    ("Notes", "comment"),
    ("Active", "active"),
    # Derived / informative columns
    ("Latest Price", "latest_price"),
    ("Previous Close", "previous_close"),
    ("Daily Change (%)", "daily_variation"),
    ("YTD Change (%)", "ytd_variation"),
    ("Analysis Change (%)", "variation_since_analysis"),
    ("Target Upside (%)", "decline_to_target"),
    ("Exchange", "exchange"),
    ("Provider Symbol", "provider_symbol"),
    ("Quote Timestamp", "quote_timestamp"),
    ("Quote Status", "quote_status"),
]


def export_to_csv(records: Optional[List[dict]] = None, db_path: Optional[str] = None) -> str:
    """
    Export watchlist to CSV string with UTF-8 encoding in English.
    Includes formula injection sanitization.
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
                row.append(f"{val:.2f}" if abs(val) >= 0.01 else f"{val:.4f}")
            else:
                sanitized_val = _sanitize_formula(str(val))
                row.append(sanitized_val)
        writer.writerow(row)

    return output.getvalue()


def export_to_excel(records: Optional[List[dict]] = None, db_path: Optional[str] = None) -> bytes:
    """
    Export watchlist to .xlsx workbook with clean styling and auto-sized columns in English.
    Includes formula injection sanitization.
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
                row_values.append("Yes" if val else "No")
            elif isinstance(val, (int, float)):
                row_values.append(round(val, 4))
            else:
                row_values.append(_sanitize_formula(str(val)))
        ws.append(row_values)

        # Style data row
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=row_idx, column=col_idx)
            c.font = data_font
            c.border = cell_border
            if col_idx in (1, 3, 10, 17, 20):  # Ticker, Currency, Active, Exchange, Status
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

    excel_output = io.BytesIO()
    wb.save(excel_output)
    return excel_output.getvalue()


def export_to_json(records: Optional[List[dict]] = None, db_path: Optional[str] = None) -> str:
    """
    Export full watchlist and quotes as structured JSON version 1.0.
    """
    if records is None:
        records = get_export_records(db_path)

    instruments_out = []
    for r in records:
        inst_dict = {
            "user_ticker": r["user_ticker"],
            "provider_symbol": r["provider_symbol"],
            "company_name": r["company_name"],
            "exchange": r["exchange"],
            "currency": r["currency"],
            "analysis_reference_price": r["analysis_reference_price"],
            "analysis_date": r["analysis_date"],
            "start_of_year_price": r["start_of_year_price"],
            "start_of_year_date": r["start_of_year_date"],
            "target_price": r["target_price"],
            "comment": r["comment"],
            "active": r["active"],
        }
        if r.get("_quote"):
            inst_dict["quote"] = r["_quote"]
        elif r.get("latest_price") is not None or r.get("quote_status"):
            inst_dict["quote"] = {
                "price": r.get("latest_price"),
                "previous_close": r.get("previous_close"),
                "quote_timestamp": r.get("quote_timestamp"),
                "fetched_at": r.get("quote_fetched_at"),
                "provider": r.get("quote_provider", ""),
                "status": r.get("quote_status", "UNAVAILABLE"),
                "error_message": None,
            }

        instruments_out.append(inst_dict)

    payload = {
        "version": "1.0",
        "app": "watchlistTracker",
        "exported_at": datetime.now().isoformat(),
        "total_positions": len(instruments_out),
        "total_instruments": len(instruments_out),
        "instruments": instruments_out,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def validate_json_backup_payload(payload: Any) -> List[dict]:
    """
    Strictly validate versioned backup payload schema before touching the database.
    
    Safety constraints:
    - Root must be a JSON object (dict).
    - 'instruments' key is mandatory and must be a list.
    - Intentionally empty backup (instruments=[]) must have 'version' or 'app' metadata to avoid
      accidentally wiping a watchlist from an ambiguous object like {}.
    - Every row must have a valid non-empty user_ticker.
    - Duplicate tickers within the backup are strictly rejected.
    - Dates and decimal numbers must have valid format and non-negative values.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid backup structure: root must be a JSON object.")

    if "instruments" not in payload:
        raise ValueError("Invalid backup structure: missing required 'instruments' list.")

    instruments_data = payload.get("instruments")
    if not isinstance(instruments_data, list):
        raise ValueError("Invalid backup structure: 'instruments' must be a list.")

    if len(instruments_data) == 0:
        if "version" not in payload and "app" not in payload:
            raise ValueError("Ambiguous backup payload: empty backup must include 'version' or 'app' metadata.")
        return []

    seen_tickers: set[str] = set()
    validated_items: List[dict] = []

    for idx, item in enumerate(instruments_data):
        if not isinstance(item, dict):
            raise ValueError(f"Row {idx + 1}: Instrument must be an object.")

        ticker = str(item.get("user_ticker") or item.get("ticker") or "").strip()
        if not ticker:
            raise ValueError(f"Row {idx + 1}: Missing required 'user_ticker'.")

        ticker_upper = ticker.upper()
        if ticker_upper in seen_tickers:
            raise ValueError(f"Row {idx + 1}: Duplicate ticker '{ticker}' in backup payload.")
        seen_tickers.add(ticker_upper)

        # Dates validation
        an_date = None
        if item.get("analysis_date"):
            try:
                an_date = date.fromisoformat(str(item["analysis_date"]).split("T")[0].split(" ")[0].strip())
            except Exception:
                raise ValueError(f"Row {idx + 1} ({ticker}): Invalid analysis_date format.")

        soy_date = None
        if item.get("start_of_year_date"):
            try:
                soy_date = date.fromisoformat(str(item["start_of_year_date"]).split("T")[0].split(" ")[0].strip())
            except Exception:
                raise ValueError(f"Row {idx + 1} ({ticker}): Invalid start_of_year_date format.")

        # Decimal numbers validation
        def _check_dec(field_name: str) -> Optional[Decimal]:
            val = item.get(field_name)
            if val is None or val == "":
                return None
            try:
                d = Decimal(str(val).strip())
                if d < 0 or d.is_nan() or d.is_infinite():
                    raise ValueError(f"Negative or non-finite value not allowed in {field_name}")
                return d
            except InvalidOperation:
                raise InvalidOperation(f"Row {idx + 1} ({ticker}): Invalid {field_name}: conversion syntax error")
            except Exception as ex:
                raise ValueError(f"Row {idx + 1} ({ticker}): Invalid {field_name}: {ex}")

        an_price = _check_dec("analysis_reference_price")
        soy_price = _check_dec("start_of_year_price")
        tgt_price = _check_dec("target_price")

        # Currency validation
        curr = str(item.get("currency") or "USD").strip().upper()
        if curr == "AUTO":
            curr = "USD"
        if not curr or len(curr) > 10:
            raise ValueError(f"Row {idx + 1} ({ticker}): Invalid currency '{curr}'.")

        # Active status
        active_raw = item.get("active", True)
        if isinstance(active_raw, str):
            is_active = active_raw.strip().lower() not in ("false", "0", "no", "f", "")
        else:
            is_active = bool(active_raw)

        validated_items.append({
            "user_ticker": ticker,
            "provider_symbol": item.get("provider_symbol") or ticker,
            "exchange": item.get("exchange", "UNKNOWN"),
            "currency": curr,
            "company_name": item.get("company_name", ticker) or ticker,
            "analysis_date": an_date,
            "analysis_reference_price": an_price,
            "start_of_year_date": soy_date,
            "start_of_year_price": soy_price,
            "target_price": tgt_price,
            "comment": item.get("comment", "") or "",
            "active": is_active,
            "quote": item.get("quote"),
        })

    return validated_items


def restore_from_json(
    json_data: str | dict,
    target_db_path: Optional[str] = None,
    create_safety_backup: bool = True,
) -> dict:
    """
    Atomic restore from a JSON backup for SQLite.
    Validates 100% of payload before modifying the database.
    """
    if isinstance(json_data, str):
        try:
            payload = json.loads(json_data)
        except Exception as e:
            raise ValueError(f"Invalid JSON format: {e}")
    else:
        payload = json_data

    # Perform strict unified schema validation
    validated_items = validate_json_backup_payload(payload)

    # Convert to ORM/Core tuples
    validated_records: List[tuple[Instrument, Optional[Quote]]] = []
    for item in validated_items:
        exchange_str = item.get("exchange", "UNKNOWN")
        try:
            exchange = Exchange(exchange_str)
        except ValueError:
            exchange = Exchange.UNKNOWN

        inst = Instrument(
            user_ticker=item["user_ticker"],
            provider_symbol=item.get("provider_symbol"),
            exchange=exchange,
            currency=item.get("currency", "USD"),
            company_name=item.get("company_name", item["user_ticker"]),
            analysis_date=item.get("analysis_date"),
            analysis_reference_price=item.get("analysis_reference_price"),
            start_of_year_date=item.get("start_of_year_date"),
            start_of_year_price=item.get("start_of_year_price"),
            target_price=item.get("target_price"),
            comment=item.get("comment", "") or "",
            active=item.get("active", True),
        )

        quote_obj = None
        if item.get("quote"):
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

            try:
                q_price = Decimal(str(q_data["price"])) if q_data.get("price") is not None else None
                q_prev = Decimal(str(q_data["previous_close"])) if q_data.get("previous_close") is not None else None
            except Exception as ex:
                raise ValueError(f"Invalid quote price: {ex}")

            quote_obj = Quote(
                price=q_price,
                previous_close=q_prev,
                quote_timestamp=q_ts,
                fetched_at=q_fetched,
                provider=q_data.get("provider", ""),
                status=status_enum,
                error_message=q_data.get("error_message"),
            )

        validated_records.append((inst, quote_obj))

    # STEP 2: Automatic safety backup of existing DB if requested
    tgt_path = get_target_db_path(target_db_path)
    if create_safety_backup:
        create_automatic_safety_backup(tgt_path, reason="pre_json_restore")

    # STEP 3: Atomic commit within a single transaction using tgt_path
    conn = get_connection(tgt_path)
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("DELETE FROM quotes")
        cursor.execute("DELETE FROM instruments")

        restored_count = 0
        restored_tickers = []

        for inst, quote_obj in validated_records:
            cursor.execute(
                """
                INSERT INTO instruments (
                    user_ticker, provider_symbol, exchange, currency, company_name,
                    analysis_date, analysis_reference_price, start_of_year_date, start_of_year_price,
                    target_price, comment, active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inst.user_ticker,
                    inst.provider_symbol,
                    inst.exchange.value if isinstance(inst.exchange, Exchange) else str(inst.exchange),
                    inst.currency,
                    inst.company_name,
                    inst.analysis_date.isoformat() if inst.analysis_date else None,
                    format(inst.analysis_reference_price, "f") if inst.analysis_reference_price is not None else None,
                    inst.start_of_year_date.isoformat() if inst.start_of_year_date else None,
                    format(inst.start_of_year_price, "f") if inst.start_of_year_price is not None else None,
                    format(inst.target_price, "f") if inst.target_price is not None else None,
                    inst.comment,
                    int(inst.active),
                ),
            )
            inst_id = cursor.lastrowid

            if quote_obj and inst_id:
                cursor.execute(
                    """
                    INSERT INTO quotes (
                        instrument_id, price, previous_close, quote_timestamp,
                        fetched_at, provider, status, error_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inst_id,
                        format(quote_obj.price, "f") if quote_obj.price is not None else None,
                        format(quote_obj.previous_close, "f") if quote_obj.previous_close is not None else None,
                        quote_obj.quote_timestamp.isoformat(sep=" ") if quote_obj.quote_timestamp else None,
                        quote_obj.fetched_at.isoformat(sep=" ") if quote_obj.fetched_at else None,
                        quote_obj.provider,
                        quote_obj.status.value,
                        quote_obj.error_message,
                    ),
                )

            restored_count += 1
            restored_tickers.append(inst.user_ticker)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "ok",
        "restored_instruments": restored_count,
        "sample_tickers": restored_tickers[:10],
        "type": "json",
    }
