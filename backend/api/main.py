"""PortfolioMaster FastAPI backend.

Exposes the existing Python business logic as a JSON REST API.
No business logic is duplicated here — every endpoint delegates to
the modules in ``src/portfoliomaster/``.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Python path: make ``import portfoliomaster`` work regardless of CWD.
# This file lives at  backend/api/main.py  →  go up 2 levels to reach the
# project root, then into ``src/``.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# ---------------------------------------------------------------------------
# Imports from the existing (untouched) business-logic package.
# ---------------------------------------------------------------------------
from portfoliomaster.core.calculations import (  # noqa: E402
    daily_variation,
    decline_to_target,
    variation_since_analysis,
)
from portfoliomaster.core.config import get_yahoo_suffix  # noqa: E402
from portfoliomaster.core.models import (  # noqa: E402
    Exchange,
    Instrument,
    Quote,
    QuoteStatus,
)
from portfoliomaster.db.connection import get_connection, init_db  # noqa: E402
from portfoliomaster.db.repository import (  # noqa: E402
    delete_instrument,
    get_all_instruments,
    get_instrument_by_ticker,
    get_quote_by_instrument_id,
    upsert_instrument,
    upsert_quote,
    wipe_database,
)
from portfoliomaster.ingest.import_session import import_spreadsheet  # noqa: E402
from portfoliomaster.ingest.normalizer import normalize  # noqa: E402
from portfoliomaster.providers.yahoo_adapter import YahooAdapter  # noqa: E402
from portfoliomaster.refresh.batch_runner import BatchRunner  # noqa: E402

# ========================================================================== #
# App setup
# ========================================================================== #


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialise the database on startup."""
    init_db()
    yield


app = FastAPI(
    title="PortfolioMaster API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Healthcheck and API information endpoint."""
    return {
        "status": "ok",
        "app": "PortfolioMaster API",
        "docs": "/docs",
        "version": "1.0.0",
    }

# ========================================================================== #
# Helpers — serialisation
# ========================================================================== #


def _to_float(val) -> Optional[float]:
    """Convert a Decimal / numeric value to float, returning None for blanks, NaN, and Inf."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _clean_str(val, default: str = "") -> str:
    """Return a clean string, converting None / NaN / NaT to default."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _clean_opt_str(val) -> Optional[str]:
    """Return a clean string, or None if missing/NaN/empty."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return s if s else None


def _instrument_to_dict(inst: Instrument) -> dict:
    return {
        "id": inst.id,
        "user_ticker": inst.user_ticker or "",
        "provider_symbol": inst.provider_symbol,
        "exchange": inst.exchange.value if isinstance(inst.exchange, Exchange) else str(inst.exchange) if inst.exchange else "",
        "currency": inst.currency or "",
        "company_name": inst.company_name or "",
        "analysis_date": inst.analysis_date.isoformat() if inst.analysis_date else None,
        "analysis_reference_price": _to_float(inst.analysis_reference_price),
        "target_price": _to_float(inst.target_price),
        "comment": inst.comment or "",
        "active": bool(inst.active),
    }


def _quote_to_dict(quote: Quote) -> dict:
    return {
        "id": quote.id,
        "instrument_id": quote.instrument_id,
        "price": _to_float(quote.price),
        "previous_close": _to_float(quote.previous_close),
        "quote_timestamp": quote.quote_timestamp.isoformat() if quote.quote_timestamp else None,
        "fetched_at": quote.fetched_at.isoformat() if quote.fetched_at else None,
        "provider": quote.provider,
        "status": quote.status.name if isinstance(quote.status, QuoteStatus) else str(quote.status) if quote.status else None,
        "error_message": quote.error_message,
    }


# ========================================================================== #
# Pydantic request models
# ========================================================================== #


class InstrumentCreate(BaseModel):
    user_ticker: str
    company_name: str = ""
    exchange: str = "AUTO"  # "AUTO" or any Exchange enum value
    currency: str = "EUR"
    target_price: Optional[float] = None
    analysis_reference_price: Optional[float] = None
    analysis_date: Optional[str] = None  # ISO date string (YYYY-MM-DD)
    comment: str = ""
    fetch_yahoo: bool = True
    manual_price: Optional[float] = None
    manual_previous_close: Optional[float] = None


class InstrumentUpdate(BaseModel):
    company_name: Optional[str] = None
    target_price: Optional[float] = None
    analysis_reference_price: Optional[float] = None
    analysis_date: Optional[str] = None
    comment: Optional[str] = None
    latest_price: Optional[float] = None
    previous_close: Optional[float] = None


class ImportConfirmRequest(BaseModel):
    instruments: list[dict]


# ========================================================================== #
# Endpoints
# ========================================================================== #


# ---- Positions (watchlist table data) ------------------------------------ #

@app.get("/api/positions")
def get_positions():
    """Full watchlist: instruments + quotes + server-computed columns."""
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                i.*,
                q.price          AS latest_price,
                q.previous_close AS previous_close,
                q.status         AS quote_status,
                q.provider       AS quote_provider,
                q.fetched_at     AS quote_fetched_at
            FROM instruments i
            LEFT JOIN quotes q ON q.instrument_id = i.id
            """,
            conn,
        )
    finally:
        conn.close()

    positions = []
    for _, row in df.iterrows():
        latest_price = _to_float(row.get("latest_price"))
        prev_close = _to_float(row.get("previous_close"))
        analysis_ref = _to_float(row.get("analysis_reference_price"))
        target = _to_float(row.get("target_price"))

        # Derived columns — computed in Python (never in TS).
        dv = daily_variation(latest_price, prev_close)
        vsa = variation_since_analysis(latest_price, analysis_ref)
        dtt = decline_to_target(target, latest_price)

        analysis_date_raw = row.get("analysis_date")
        analysis_date_str = None
        if analysis_date_raw is not None:
            try:
                if not pd.isna(analysis_date_raw):
                    analysis_date_str = str(analysis_date_raw)
            except (TypeError, ValueError):
                analysis_date_str = str(analysis_date_raw)

        row_id = row.get("id")
        try:
            row_id_int = int(row_id) if row_id is not None and not pd.isna(row_id) else None
        except (TypeError, ValueError):
            row_id_int = None

        row_active = row.get("active")
        active_bool = bool(row_active) if row_active is not None and not pd.isna(row_active) else True

        positions.append(
            {
                "id": row_id_int,
                "user_ticker": _clean_str(row.get("user_ticker")),
                "provider_symbol": _clean_opt_str(row.get("provider_symbol")),
                "exchange": _clean_str(row.get("exchange")),
                "currency": _clean_str(row.get("currency")),
                "company_name": _clean_str(row.get("company_name")),
                "analysis_date": analysis_date_str,
                "analysis_reference_price": analysis_ref,
                "target_price": target,
                "comment": _clean_str(row.get("comment")),
                "active": active_bool,
                # Quote data
                "latest_price": latest_price,
                "previous_close": prev_close,
                "quote_status": _clean_opt_str(row.get("quote_status")),
                "quote_provider": _clean_opt_str(row.get("quote_provider")),
                "quote_fetched_at": _clean_opt_str(row.get("quote_fetched_at")),
                # Computed columns
                "daily_variation": _to_float(dv.daily_variation),
                "daily_variation_valid": bool(dv.daily_variation_valid),
                "variation_since_analysis": _to_float(vsa.variation_since_analysis),
                "variation_since_analysis_valid": bool(vsa.variation_since_analysis_valid),
                "decline_to_target": _to_float(dtt.decline_to_target),
                "decline_to_target_valid": bool(dtt.decline_to_target_valid),
            }
        )

    return {"positions": positions, "count": len(positions)}


@app.get("/api/metrics")
def get_metrics():
    """Summary metrics: number of positions, best/worst performer, average daily change."""
    pos_data = get_positions()["positions"]
    total = len(pos_data)
    valid_daily = [
        p for p in pos_data
        if p.get("daily_variation_valid") and p.get("daily_variation") is not None
    ]

    best = None
    worst = None
    avg_change = None
    positive_count = 0
    negative_count = 0
    neutral_count = 0

    if valid_daily:
        sorted_daily = sorted(valid_daily, key=lambda x: x["daily_variation"])
        worst_p = sorted_daily[0]
        best_p = sorted_daily[-1]

        worst = {
            "user_ticker": worst_p["user_ticker"],
            "company_name": worst_p["company_name"],
            "daily_variation": worst_p["daily_variation"],
            "latest_price": worst_p["latest_price"],
            "currency": worst_p["currency"],
        }
        best = {
            "user_ticker": best_p["user_ticker"],
            "company_name": best_p["company_name"],
            "daily_variation": best_p["daily_variation"],
            "latest_price": best_p["latest_price"],
            "currency": best_p["currency"],
        }

        avg_change = round(sum(p["daily_variation"] for p in valid_daily) / len(valid_daily), 2)
        positive_count = sum(1 for p in valid_daily if p["daily_variation"] > 0)
        negative_count = sum(1 for p in valid_daily if p["daily_variation"] < 0)
        neutral_count = sum(1 for p in valid_daily if p["daily_variation"] == 0)

    return {
        "total_positions": total,
        "positions_with_quotes": len(valid_daily),
        "best_performer": best,
        "worst_performer": worst,
        "average_daily_change": avg_change,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
    }


# ---- Instruments CRUD ---------------------------------------------------- #

@app.get("/api/instruments")
def list_instruments():
    """All active instruments (for dropdowns / selects)."""
    instruments = get_all_instruments()
    return {
        "instruments": [_instrument_to_dict(inst) for inst in instruments],
        "count": len(instruments),
    }


@app.get("/api/instruments/{ticker}")
def get_instrument(ticker: str):
    """Single instrument with its quote."""
    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    result = _instrument_to_dict(inst)
    quote = get_quote_by_instrument_id(inst.id) if inst.id else None
    result["quote"] = _quote_to_dict(quote) if quote else None
    return result


@app.post("/api/instruments", status_code=201)
def create_instrument(data: InstrumentCreate):
    """Create a new instrument, optionally fetching a Yahoo quote."""
    ticker_clean = data.user_ticker.strip()
    if not ticker_clean:
        raise HTTPException(status_code=400, detail="user_ticker is required")

    curr = data.currency.strip().upper()

    # Normalise ticker → provider symbol
    norm_ticker, detected_exchange = normalize(ticker_clean, curr)

    if data.exchange == "AUTO":
        exchange = detected_exchange
    else:
        try:
            exchange = Exchange(data.exchange)
        except ValueError:
            exchange = detected_exchange

    suffix = get_yahoo_suffix(ticker_clean, exchange, curr)
    if suffix and not norm_ticker.upper().endswith(suffix.upper()):
        provider_symbol = f"{norm_ticker}{suffix}"
    else:
        provider_symbol = norm_ticker

    ref_dec = Decimal(str(data.analysis_reference_price)) if data.analysis_reference_price and data.analysis_reference_price > 0 else None
    tgt_dec = Decimal(str(data.target_price)) if data.target_price and data.target_price > 0 else None

    analysis_dt = None
    if data.analysis_date:
        try:
            analysis_dt = date.fromisoformat(data.analysis_date)
        except ValueError:
            analysis_dt = date.today()
    else:
        analysis_dt = date.today()

    # If analysis reference price is missing but Yahoo fetch is enabled, attempt to look it up
    if ref_dec is None and data.fetch_yahoo and provider_symbol and analysis_dt:
        hist_p = _fetch_historical_quote_for_date(provider_symbol, analysis_dt)
        if hist_p is not None and hist_p > 0:
            ref_dec = Decimal(str(hist_p))

    inst = Instrument(
        user_ticker=ticker_clean,
        provider_symbol=provider_symbol,
        exchange=exchange,
        currency=curr,
        company_name=data.company_name.strip() or ticker_clean,
        analysis_date=analysis_dt,
        analysis_reference_price=ref_dec,
        target_price=tgt_dec,
        comment=data.comment.strip(),
        active=True,
    )

    try:
        upsert_instrument(inst)
        saved_inst = get_instrument_by_ticker(ticker_clean)
        inst_id = saved_inst.id if saved_inst else None
        quote_info: dict | None = None

        # Manual price takes precedence
        if data.manual_price and data.manual_price > 0 and inst_id:
            q = Quote(
                instrument_id=inst_id,
                price=Decimal(str(data.manual_price)),
                previous_close=(
                    Decimal(str(data.manual_previous_close))
                    if data.manual_previous_close and data.manual_previous_close > 0
                    else None
                ),
                quote_timestamp=datetime.now(),
                fetched_at=datetime.now(),
                provider="Manual",
                status=QuoteStatus.FRESH,
            )
            upsert_quote(q)
            quote_info = {"source": "manual", "price": data.manual_price}

        elif data.fetch_yahoo and provider_symbol and inst_id:
            try:
                adapter = YahooAdapter()
                quotes = adapter.fetch([provider_symbol])
                if provider_symbol in quotes and quotes[provider_symbol].is_valid():
                    q = quotes[provider_symbol]
                    q.instrument_id = inst_id
                    upsert_quote(q)
                    quote_info = {"source": "yahoo", "price": _to_float(q.price)}
                else:
                    quote_info = {
                        "source": "yahoo",
                        "price": None,
                        "note": f"Yahoo did not return a price for '{provider_symbol}'",
                    }
            except Exception as e:
                quote_info = {"source": "yahoo", "price": None, "error": str(e)}

        return {
            "status": "ok",
            "instrument": _instrument_to_dict(saved_inst) if saved_inst else _instrument_to_dict(inst),
            "quote": quote_info,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/instruments/{ticker}")
def update_instrument(ticker: str, data: InstrumentUpdate):
    """Update an existing instrument and optionally its manual quote."""
    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    if data.company_name is not None:
        inst.company_name = data.company_name.strip() or inst.user_ticker
    if data.target_price is not None:
        inst.target_price = Decimal(str(data.target_price)) if data.target_price > 0 else None
    if data.analysis_reference_price is not None:
        inst.analysis_reference_price = Decimal(str(data.analysis_reference_price)) if data.analysis_reference_price > 0 else None
    if data.analysis_date is not None:
        if data.analysis_date.strip():
            try:
                inst.analysis_date = date.fromisoformat(data.analysis_date.strip())
            except ValueError:
                pass
        else:
            inst.analysis_date = None
    if data.comment is not None:
        inst.comment = data.comment.strip()

    upsert_instrument(inst)

    # Optionally update the quote (manual edit)
    if data.latest_price is not None and data.latest_price > 0 and inst.id:
        q = Quote(
            instrument_id=inst.id,
            price=Decimal(str(data.latest_price)),
            previous_close=(
                Decimal(str(data.previous_close))
                if data.previous_close and data.previous_close > 0
                else None
            ),
            quote_timestamp=datetime.now(),
            fetched_at=datetime.now(),
            provider="Manual",
            status=QuoteStatus.FRESH,
        )
        upsert_quote(q)

    return {"status": "ok", "instrument": _instrument_to_dict(inst)}


def _fetch_historical_quote_for_date(provider_symbol: str, target_date: date) -> Optional[float]:
    """Fetch closing price on or shortly after target_date from Yahoo Finance."""
    if not provider_symbol or not target_date:
        return None
    try:
        t = yf.Ticker(provider_symbol)
        start_str = target_date.isoformat()
        end_str = (target_date + timedelta(days=5)).isoformat()
        hist = t.history(start=start_str, end=end_str)
        if not hist.empty and "Close" in hist:
            price = hist["Close"].iloc[0]
            if pd.notna(price) and float(price) > 0:
                return round(float(price), 4)
    except Exception:
        pass
    return None


@app.post("/api/instruments/{ticker}/fetch-analysis-price")
def fetch_analysis_price_endpoint(ticker: str, target_date: Optional[str] = None):
    """Fetch historical quote from Yahoo Finance for instrument's analysis_date."""
    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    dt = None
    if target_date:
        try:
            dt = date.fromisoformat(target_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")
    elif inst.analysis_date:
        dt = inst.analysis_date

    if not dt:
        raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no analysis_date specified")

    if not inst.provider_symbol:
        raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol for Yahoo Finance")

    price = _fetch_historical_quote_for_date(inst.provider_symbol, dt)
    if price is None:
        raise HTTPException(
            status_code=404,
            detail=f"No historical quote found on Yahoo Finance for '{inst.provider_symbol}' around {dt.isoformat()}",
        )

    inst.analysis_date = dt
    inst.analysis_reference_price = Decimal(str(price))
    upsert_instrument(inst)

    return {
        "status": "ok",
        "ticker": ticker,
        "analysis_date": dt.isoformat(),
        "analysis_reference_price": price,
    }


@app.post("/api/instruments/resolve-missing-analysis-prices")
def resolve_missing_analysis_prices():
    """Auto-resolve analysis_reference_price from Yahoo Finance for instruments with analysis_date."""
    instruments = get_all_instruments()
    updated = 0
    failed = 0
    skipped = 0

    for inst in instruments:
        if inst.analysis_reference_price is not None and inst.analysis_reference_price > 0:
            skipped += 1
            continue
        if not inst.analysis_date or not inst.provider_symbol:
            skipped += 1
            continue

        price = _fetch_historical_quote_for_date(inst.provider_symbol, inst.analysis_date)
        if price is not None:
            inst.analysis_reference_price = Decimal(str(price))
            upsert_instrument(inst)
            updated += 1
        else:
            failed += 1

    return {
        "status": "ok",
        "updated": updated,
        "failed": failed,
        "skipped": skipped,
        "total": len(instruments),
    }


@app.delete("/api/instruments/{ticker}")
def remove_instrument(ticker: str):
    """Delete an instrument and its quotes."""
    success = delete_instrument(ticker)
    if not success:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
    return {"status": "ok", "deleted": ticker}


# ---- Yahoo refresh ------------------------------------------------------- #

@app.post("/api/instruments/{ticker}/refresh")
def refresh_single(ticker: str):
    """Refresh the quote for one instrument from Yahoo Finance."""
    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
    if not inst.provider_symbol or not inst.id:
        raise HTTPException(status_code=400, detail="Instrument has no provider symbol or ID")

    try:
        adapter = YahooAdapter()
        quotes = adapter.fetch([inst.provider_symbol])
        if inst.provider_symbol in quotes and quotes[inst.provider_symbol].is_valid():
            q = quotes[inst.provider_symbol]
            q.instrument_id = inst.id
            upsert_quote(q)
            return {
                "status": "ok",
                "price": _to_float(q.price),
                "previous_close": _to_float(q.previous_close),
                "provider": q.provider,
                "quote_status": q.status.name,
            }
        return {
            "status": "unavailable",
            "detail": f"Yahoo returned no price for {inst.provider_symbol}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/refresh")
def refresh_all():
    """Batch refresh every instrument's quote from Yahoo Finance."""
    instruments = get_all_instruments()
    if not instruments:
        return {"status": "ok", "updated": 0, "failed": 0, "total": 0}

    # Re-normalise symbols before fetching (mirrors render_refresh_control)
    for inst in instruments:
        norm_ticker, exchange = normalize(inst.user_ticker, inst.currency)
        suffix = get_yahoo_suffix(inst.user_ticker, exchange, inst.currency)
        expected = (
            f"{norm_ticker}{suffix}"
            if suffix and not norm_ticker.upper().endswith(suffix.upper())
            else norm_ticker
        )
        if inst.provider_symbol != expected or inst.exchange != exchange:
            inst.provider_symbol = expected
            inst.exchange = exchange
            upsert_instrument(inst)

    symbols = [inst.provider_symbol for inst in instruments if inst.provider_symbol]
    provider = YahooAdapter()
    runner = BatchRunner(provider=provider)
    quotes = runner.run(symbols)

    instrument_map = {inst.provider_symbol: inst.id for inst in instruments}
    updated = 0
    failed = 0
    for symbol, quote in quotes.items():
        quote.instrument_id = instrument_map.get(symbol)
        if quote.instrument_id:
            upsert_quote(quote)
            if quote.is_valid():
                updated += 1
            else:
                failed += 1

    return {"status": "ok", "updated": updated, "failed": failed, "total": len(instruments)}


# ---- CSV / Excel import -------------------------------------------------- #

@app.post("/api/import/preview")
async def import_preview(file: UploadFile = File(...)):
    """Upload a CSV/Excel file, parse and validate it, return a preview."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xlsx"):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        instruments, errors, unresolved, warnings = import_spreadsheet(tmp_path, file.filename)
    finally:
        os.remove(tmp_path)

    return {
        "instruments": [_instrument_to_dict(inst) for inst in instruments],
        "errors": errors,
        "unresolved": unresolved,
        "warnings": warnings,
        "valid_count": len(instruments),
    }


@app.post("/api/import/confirm")
def import_confirm(data: ImportConfirmRequest):
    """Commit previously previewed instruments to the database."""
    committed = 0
    commit_errors: list[str] = []

    for inst_dict in data.instruments:
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

            analysis_dt = None
            if inst_dict.get("analysis_date"):
                try:
                    analysis_dt = date.fromisoformat(str(inst_dict["analysis_date"]))
                except ValueError:
                    pass

            inst = Instrument(
                user_ticker=ticker,
                provider_symbol=inst_dict.get("provider_symbol"),
                exchange=exchange,
                currency=inst_dict.get("currency", ""),
                company_name=inst_dict.get("company_name", ticker),
                analysis_date=analysis_dt,
                analysis_reference_price=Decimal(str(ref_price)) if ref_price is not None else None,
                target_price=Decimal(str(tgt_price)) if tgt_price is not None else None,
                comment=inst_dict.get("comment", ""),
                active=inst_dict.get("active", True),
            )
            upsert_instrument(inst)
            committed += 1
        except Exception as e:
            commit_errors.append(f"Error importing '{inst_dict.get('user_ticker', '?')}': {e}")

    return {"status": "ok", "committed": committed, "errors": commit_errors}


# ---- Database management ------------------------------------------------- #

@app.delete("/api/database")
def wipe_db():
    """Wipe all data from the database (instruments + quotes)."""
    wipe_database()
    return {"status": "ok", "detail": "Database wiped"}
