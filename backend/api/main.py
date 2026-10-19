"""PortfolioMaster FastAPI backend.

Exposes the existing Python business logic as a JSON REST API.
No business logic is duplicated here — every endpoint delegates to
the modules in ``src/portfoliomaster/``.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
import io

import pandas as pd
import yfinance as yf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
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
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports from the existing business-logic package.
# ---------------------------------------------------------------------------
from portfoliomaster.core.calculations import (  # noqa: E402
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)
from portfoliomaster.core.config import (  # noqa: E402
    get_yahoo_suffix,
    get_refresh_interval,
    get_batch_size,
)
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
    update_instrument_by_id,
    upsert_instrument,
    upsert_quote,
    wipe_database,
)
from portfoliomaster.ingest.import_session import import_spreadsheet  # noqa: E402
from portfoliomaster.ingest.normalizer import normalize  # noqa: E402
from portfoliomaster.providers.yahoo_adapter import YahooAdapter  # noqa: E402
from portfoliomaster.refresh.batch_runner import BatchRunner  # noqa: E402
from portfoliomaster.backup import (  # noqa: E402
    create_automatic_safety_backup,
    create_sqlite_backup,
    export_to_csv,
    export_to_excel,
    export_to_json,
    list_automatic_backups,
    restore_automatic_backup,
    restore_from_json,
    restore_sqlite_backup,
    validate_sqlite_backup,
)

# ========================================================================== #
# Logging & Runtime State
# ========================================================================== #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("portfoliomaster.api")

_refresh_lock = threading.Lock()
_state: dict = {
    "last_refresh_at": None,
    "last_refresh_result": None,
}


async def background_refresh_loop():
    """Background worker that periodically refreshes market data quotes."""
    # Give the app a couple seconds to complete startup before initial check
    await asyncio.sleep(2)
    while True:
        try:
            interval = get_refresh_interval()
            if interval <= 0:
                logger.info("[AutoRefresh] Automatic refresh disabled (REFRESH_INTERVAL_SECONDS <= 0).")
                await asyncio.sleep(60)
                continue

            logger.info(
                f"[AutoRefresh] Worker running. Interval: {interval:.0f}s | "
                f"Batch size: {get_batch_size()} tickers."
            )
            await asyncio.sleep(interval)

            instruments = get_all_instruments()
            if not instruments:
                logger.info("[AutoRefresh] No instruments registered. Skipping scheduled refresh.")
                continue

            logger.info(
                f"[AutoRefresh] Starting scheduled refresh for {len(instruments)} instruments "
                f"(batch size: {get_batch_size()})..."
            )
            result = await asyncio.to_thread(_execute_refresh_all)
            logger.info(
                f"[AutoRefresh] Refresh finished: {result.get('updated', 0)} updated, "
                f"{result.get('failed', 0)} failed of {result.get('total', 0)} total."
            )
        except asyncio.CancelledError:
            logger.info("[AutoRefresh] Background worker stopping.")
            break
        except Exception as e:
            logger.error(f"[AutoRefresh] Unexpected error during refresh cycle: {e}")
            await asyncio.sleep(5)


# ========================================================================== #
# App setup
# ========================================================================== #


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialise database on startup and run background refresh worker."""
    init_db()
    task = asyncio.create_task(background_refresh_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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
        "start_of_year_date": inst.start_of_year_date.isoformat() if inst.start_of_year_date else None,
        "start_of_year_price": _to_float(inst.start_of_year_price),
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
    start_of_year_price: Optional[float] = None
    start_of_year_date: Optional[str] = None  # ISO date string (YYYY-MM-DD)
    comment: str = ""
    fetch_yahoo: bool = True
    manual_price: Optional[float] = None
    manual_previous_close: Optional[float] = None


class InstrumentUpdate(BaseModel):
    new_ticker: Optional[str] = None
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    target_price: Optional[float] = None
    analysis_reference_price: Optional[float] = None
    analysis_date: Optional[str] = None
    start_of_year_price: Optional[float] = None
    start_of_year_date: Optional[str] = None
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
        start_of_year_price = _to_float(row.get("start_of_year_price"))
        target = _to_float(row.get("target_price"))

        # Derived columns — computed in Python (never in TS).
        dv = daily_variation(latest_price, prev_close)
        vsa = variation_since_analysis(latest_price, analysis_ref)
        ytd = ytd_variation(latest_price, start_of_year_price)
        dtt = decline_to_target(target, latest_price)

        analysis_date_raw = row.get("analysis_date")
        analysis_date_str = None
        if analysis_date_raw is not None:
            try:
                if not pd.isna(analysis_date_raw):
                    analysis_date_str = str(analysis_date_raw)
            except (TypeError, ValueError):
                analysis_date_str = str(analysis_date_raw)

        start_of_year_date_raw = row.get("start_of_year_date")
        start_of_year_date_str = None
        if start_of_year_date_raw is not None:
            try:
                if not pd.isna(start_of_year_date_raw):
                    start_of_year_date_str = str(start_of_year_date_raw)
            except (TypeError, ValueError):
                start_of_year_date_str = str(start_of_year_date_raw)

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
                "start_of_year_date": start_of_year_date_str,
                "start_of_year_price": start_of_year_price,
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
                "ytd_variation": _to_float(ytd.ytd_variation),
                "ytd_variation_valid": bool(ytd.ytd_variation_valid),
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


@app.get("/api/instruments/check-yahoo")
def check_yahoo_ticker(ticker: str, currency: Optional[str] = None):
    """Check if a ticker is valid and available on Yahoo Finance."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="El ticker es requerido")

    curr = (currency or "").strip().upper()
    norm_ticker, detected_exchange = normalize(ticker.strip(), curr)
    suffix = get_yahoo_suffix(ticker.strip(), detected_exchange, curr)
    if suffix and not norm_ticker.upper().endswith(suffix.upper()):
        provider_symbol = f"{norm_ticker}{suffix}"
    else:
        provider_symbol = norm_ticker

    try:
        t = yf.Ticker(provider_symbol)
        price = None
        prev_close = None
        resolved_currency = curr or None

        # 1. Quick check using fast_info
        try:
            fi = getattr(t, "fast_info", None)
            if fi:
                lp = getattr(fi, "last_price", None)
                if lp is not None and not math.isnan(lp) and lp > 0:
                    price = round(float(lp), 4)
                pc = getattr(fi, "previous_close", None)
                if pc is not None and not math.isnan(pc) and pc > 0:
                    prev_close = round(float(pc), 4)
                c_val = getattr(fi, "currency", None)
                if c_val:
                    resolved_currency = str(c_val).upper()
        except Exception:
            pass

        # 2. Fallback check using history
        if price is None:
            hist = t.history(period="5d")
            if not hist.empty and "Close" in hist and len(hist) > 0:
                p_val = hist["Close"].iloc[-1]
                if pd.notna(p_val) and float(p_val) > 0:
                    price = round(float(p_val), 4)
                    if len(hist) > 1:
                        prev_val = hist["Close"].iloc[-2]
                        if pd.notna(prev_val) and float(prev_val) > 0:
                            prev_close = round(float(prev_val), 4)

        # Resolve company name if available
        comp_name = None
        try:
            inf = getattr(t, "info", None)
            if isinstance(inf, dict):
                comp_name = inf.get("shortName") or inf.get("longName")
        except Exception:
            pass

        if price is not None and price > 0:
            return {
                "status": "ok",
                "available": True,
                "ticker": ticker.strip(),
                "provider_symbol": provider_symbol,
                "exchange": detected_exchange.value if isinstance(detected_exchange, Exchange) else str(detected_exchange),
                "currency": resolved_currency,
                "company_name": comp_name,
                "price": price,
                "previous_close": prev_close,
                "message": f"Ticker disponible en Yahoo Finance ({provider_symbol})",
            }
        else:
            return {
                "status": "ok",
                "available": False,
                "ticker": ticker.strip(),
                "provider_symbol": provider_symbol,
                "company_name": comp_name,
                "message": f"Yahoo Finance no devolvió cotización para '{provider_symbol}'",
            }
    except Exception as e:
        return {
            "status": "ok",
            "available": False,
            "ticker": ticker.strip(),
            "provider_symbol": provider_symbol,
            "message": f"Error al consultar Yahoo Finance: {str(e)}",
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

    curr = (data.currency or "").strip().upper()
    if curr == "AUTO":
        curr = ""

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

    # Check if currency or company_name need auto-resolution
    company_name_clean = (data.company_name or "").strip()
    is_name_auto = not company_name_clean or company_name_clean.upper() == "AUTO"
    is_curr_auto = not curr or curr == "AUTO"

    if (is_name_auto or is_curr_auto) and provider_symbol:
        try:
            yt = yf.Ticker(provider_symbol)
            if is_curr_auto:
                fi_curr = getattr(getattr(yt, "fast_info", None), "currency", None)
                if fi_curr:
                    curr = str(fi_curr).upper()
            if is_name_auto:
                inf = getattr(yt, "info", None)
                if isinstance(inf, dict):
                    resolved_name = inf.get("shortName") or inf.get("longName")
                    if resolved_name:
                        company_name_clean = str(resolved_name).strip()
        except Exception:
            pass

    # Fallback currency if still not resolved
    if not curr:
        DEFAULT_EXCHANGE_CURRENCIES = {
            Exchange.US: "USD",
            Exchange.UK: "GBP",
            Exchange.SWITZERLAND: "CHF",
            Exchange.JAPAN: "JPY",
            Exchange.CANADA: "CAD",
            Exchange.AUSTRALIA: "AUD",
            Exchange.SWEDEN: "SEK",
            Exchange.NORWAY: "NOK",
            Exchange.DENMARK: "DKK",
            Exchange.POLAND: "PLN",
            Exchange.BRAZIL: "BRL",
            Exchange.MEXICO: "MXN",
            Exchange.HONG_KONG: "HKD",
            Exchange.SINGAPORE: "SGD",
        }
        curr = DEFAULT_EXCHANGE_CURRENCIES.get(exchange, "EUR")

    if not company_name_clean or company_name_clean.upper() == "AUTO":
        company_name_clean = ticker_clean

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

    soy_dec = Decimal(str(data.start_of_year_price)) if data.start_of_year_price and data.start_of_year_price > 0 else None
    soy_dt = None
    if data.start_of_year_date:
        try:
            soy_dt = date.fromisoformat(data.start_of_year_date)
        except ValueError:
            pass

    # If start of year reference price is missing but Yahoo fetch is enabled, attempt to look it up
    if soy_dec is None and data.fetch_yahoo and provider_symbol:
        hist_ytd = _fetch_start_of_year_quote(provider_symbol, date.today().year)
        if hist_ytd is not None:
            soy_dec = Decimal(str(hist_ytd[0]))
            soy_dt = hist_ytd[1]

    inst = Instrument(
        user_ticker=ticker_clean,
        provider_symbol=provider_symbol,
        exchange=exchange,
        currency=curr,
        company_name=company_name_clean,
        analysis_date=analysis_dt,
        analysis_reference_price=ref_dec,
        start_of_year_date=soy_dt,
        start_of_year_price=soy_dec,
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

    ticker_changed = False
    if data.new_ticker and data.new_ticker.strip():
        new_t = data.new_ticker.strip()
        if new_t.upper() != ticker.upper():
            existing = get_instrument_by_ticker(new_t)
            if existing and existing.id != inst.id:
                raise HTTPException(status_code=400, detail=f"El ticker '{new_t}' ya existe en el portfolio.")
            inst.user_ticker = new_t
            ticker_changed = True

    if data.currency is not None and data.currency.strip() and data.currency.strip().upper() != "AUTO":
        inst.currency = data.currency.strip().upper()

    if ticker_changed or (data.exchange is not None and data.exchange.strip()):
        curr_for_norm = inst.currency or ""
        norm_ticker, detected_exchange = normalize(inst.user_ticker, curr_for_norm)

        if data.exchange is not None and data.exchange.strip() and data.exchange.strip().upper() != "AUTO":
            try:
                inst.exchange = Exchange(data.exchange.strip())
            except ValueError:
                inst.exchange = detected_exchange
        elif detected_exchange != Exchange.UNKNOWN:
            inst.exchange = detected_exchange

        suffix = get_yahoo_suffix(inst.user_ticker, inst.exchange, curr_for_norm)
        if suffix and not norm_ticker.upper().endswith(suffix.upper()):
            inst.provider_symbol = f"{norm_ticker}{suffix}"
        else:
            inst.provider_symbol = norm_ticker

    if data.company_name is not None:
        c_name = data.company_name.strip()
        if c_name and c_name.upper() != "AUTO":
            inst.company_name = c_name
        elif ticker_changed:
            resolved_name = None
            if inst.provider_symbol:
                try:
                    yt = yf.Ticker(inst.provider_symbol)
                    inf = getattr(yt, "info", None)
                    if isinstance(inf, dict):
                        resolved_name = inf.get("shortName") or inf.get("longName")
                except Exception:
                    pass
            inst.company_name = resolved_name or inst.user_ticker
        else:
            inst.company_name = inst.user_ticker
    elif ticker_changed:
        resolved_name = None
        if inst.provider_symbol:
            try:
                yt = yf.Ticker(inst.provider_symbol)
                inf = getattr(yt, "info", None)
                if isinstance(inf, dict):
                    resolved_name = inf.get("shortName") or inf.get("longName")
            except Exception:
                pass
        inst.company_name = resolved_name or inst.user_ticker

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
    if data.start_of_year_price is not None:
        inst.start_of_year_price = Decimal(str(data.start_of_year_price)) if data.start_of_year_price > 0 else None
    if data.start_of_year_date is not None:
        if data.start_of_year_date.strip():
            try:
                inst.start_of_year_date = date.fromisoformat(data.start_of_year_date.strip())
            except ValueError:
                pass
        else:
            inst.start_of_year_date = None
    if data.comment is not None:
        inst.comment = data.comment.strip()

    update_instrument_by_id(inst)

    # Update quote
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
    elif ticker_changed and inst.id and inst.provider_symbol:
        try:
            adapter = YahooAdapter()
            quotes = adapter.fetch([inst.provider_symbol])
            if inst.provider_symbol in quotes and quotes[inst.provider_symbol].is_valid():
                q = quotes[inst.provider_symbol]
                q.instrument_id = inst.id
                upsert_quote(q)
        except Exception as e:
            logger.debug(f"Could not fetch fresh quote on ticker rename for {inst.provider_symbol}: {e}")

    return {"status": "ok", "instrument": _instrument_to_dict(inst)}


def _fetch_start_of_year_quote(
    provider_symbol: str, year: Optional[int] = None
) -> Optional[tuple[float, date]]:
    """Fetch closing price and trading date for the beginning of the given (or current) year."""
    y = year or date.today().year
    target_date = date(y, 1, 1)
    if not provider_symbol:
        return None
    try:
        t = yf.Ticker(provider_symbol)
        start_str = target_date.isoformat()
        end_str = (target_date + timedelta(days=10)).isoformat()
        hist = t.history(start=start_str, end=end_str)
        if hist.empty or "Close" not in hist:
            hist = t.history(period="ytd")
        if not hist.empty and "Close" in hist:
            close_series = hist["Close"].dropna()
            if not close_series.empty:
                price = close_series.iloc[0]
                idx = close_series.index[0]
                actual_dt = (
                    idx.date()
                    if hasattr(idx, "date")
                    else (
                        idx.to_pydatetime().date()
                        if hasattr(idx, "to_pydatetime")
                        else target_date
                    )
                )
                if float(price) > 0:
                    return round(float(price), 4), actual_dt
    except Exception:
        pass
    return None


def _fetch_historical_quote_and_date(
    provider_symbol: str, target_date: date, window_days: int = 10
) -> Optional[tuple[float, date]]:
    """Fetch closing price and trading date on or before target_date with resilient lookback and fallback."""
    if not provider_symbol or not target_date:
        return None
    try:
        # Special case: Start of Year (Jan 1) looks forward to the first trading day of January
        if target_date.month == 1 and target_date.day == 1:
            return _fetch_start_of_year_quote(provider_symbol, target_date.year)

        t = yf.Ticker(provider_symbol)

        # 1. Historical lookback window: window_days before target_date up to target_date + 1 day
        start_str = (target_date - timedelta(days=window_days)).isoformat()
        end_str = (target_date + timedelta(days=1)).isoformat()
        hist = t.history(start=start_str, end=end_str)

        if not hist.empty and "Close" in hist:
            valid_rows = []
            for idx, row in hist.iterrows():
                row_dt = idx.date() if hasattr(idx, "date") else idx.to_pydatetime().date()
                val = row["Close"]
                if row_dt <= target_date and pd.notna(val) and float(val) > 0:
                    valid_rows.append((float(val), row_dt))

            if valid_rows:
                # Select the most recent available trading day's close on or before target_date
                price, actual_dt = valid_rows[-1]
                return round(price, 4), actual_dt

        # 2. Resilient fallback for today / closed market / weekends / intraday
        price = None
        actual_dt = target_date

        try:
            fi = getattr(t, "fast_info", None)
            if fi:
                lp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
                if lp is not None and not math.isnan(float(lp)) and float(lp) > 0:
                    price = float(lp)
                if price is None:
                    pc = getattr(fi, "previous_close", None) or getattr(fi, "regularMarketPreviousClose", None)
                    if pc is not None and not math.isnan(float(pc)) and float(pc) > 0:
                        price = float(pc)
        except Exception:
            pass

        if price is None:
            try:
                hist_recent = t.history(period="5d")
                if not hist_recent.empty and "Close" in hist_recent:
                    recent_series = hist_recent["Close"].dropna()
                    if not recent_series.empty:
                        last_val = recent_series.iloc[-1]
                        if float(last_val) > 0:
                            price = float(last_val)
                            last_idx = recent_series.index[-1]
                            actual_dt = last_idx.date() if hasattr(last_idx, "date") else target_date
            except Exception:
                pass

        if price is not None and price > 0:
            return round(price, 4), actual_dt

    except Exception as e:
        logger.debug(f"Error in _fetch_historical_quote_and_date for {provider_symbol}: {e}")

    return None


def _fetch_historical_quote_for_date(provider_symbol: str, target_date: date) -> Optional[float]:
    """Fetch closing price on or shortly before target_date from Yahoo Finance."""
    res = _fetch_historical_quote_and_date(provider_symbol, target_date, window_days=10)
    return res[0] if res else None


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


@app.post("/api/instruments/{ticker}/fetch-ytd-price")
def fetch_ytd_price_endpoint(ticker: str, target_year: Optional[int] = None):
    """Fetch start of year quote from Yahoo Finance for instrument for current (or given) year."""
    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    if not inst.provider_symbol:
        raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol for Yahoo Finance")

    year = target_year or date.today().year
    res = _fetch_start_of_year_quote(inst.provider_symbol, year)
    if res is None:
        raise HTTPException(
            status_code=404,
            detail=f"No start-of-year quote found on Yahoo Finance for '{inst.provider_symbol}' for year {year}",
        )

    price, dt = res
    inst.start_of_year_date = dt
    inst.start_of_year_price = Decimal(str(price))
    upsert_instrument(inst)

    return {
        "status": "ok",
        "ticker": ticker,
        "start_of_year_date": dt.isoformat(),
        "start_of_year_price": price,
    }


def _execute_resolve_missing_analysis_prices() -> dict:
    """Core logic to auto-resolve analysis_reference_price from Yahoo Finance for instruments with analysis_date."""
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


@app.post("/api/instruments/resolve-missing-analysis-prices")
def resolve_missing_analysis_prices():
    """Auto-resolve analysis_reference_price from Yahoo Finance for instruments with analysis_date."""
    return _execute_resolve_missing_analysis_prices()


def _execute_resolve_missing_ytd_prices() -> dict:
    """Core logic to auto-resolve start_of_year_price from Yahoo Finance for instruments for the current year."""
    current_year = date.today().year
    instruments = get_all_instruments()
    updated = 0
    failed = 0
    skipped = 0

    for inst in instruments:
        if (
            inst.start_of_year_price is not None
            and inst.start_of_year_price > 0
            and inst.start_of_year_date is not None
            and inst.start_of_year_date.year == current_year
        ):
            skipped += 1
            continue
        if not inst.provider_symbol:
            skipped += 1
            continue

        res = _fetch_start_of_year_quote(inst.provider_symbol, current_year)
        if res is not None:
            price, actual_dt = res
            inst.start_of_year_price = Decimal(str(price))
            inst.start_of_year_date = actual_dt
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


@app.post("/api/instruments/resolve-missing-ytd-prices")
def resolve_missing_ytd_prices():
    """Auto-resolve start_of_year_price from Yahoo Finance for instruments for current year."""
    return _execute_resolve_missing_ytd_prices()


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
    """Refresh the quote for one instrument from Yahoo Finance and auto-resolve missing reference prices."""
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

            inst_modified = False

            # Auto-resolve Analysis reference price if missing
            if (
                inst.analysis_reference_price is None
                or inst.analysis_reference_price <= 0
            ):
                target_dt = inst.analysis_date or date.today()
                hist_p = _fetch_historical_quote_for_date(inst.provider_symbol, target_dt)
                if hist_p is not None and hist_p > 0:
                    inst.analysis_reference_price = Decimal(str(hist_p))
                    if not inst.analysis_date:
                        inst.analysis_date = target_dt
                    inst_modified = True

            # Auto-resolve YTD start of year price if missing or outdated
            current_year = date.today().year
            if (
                inst.start_of_year_price is None
                or inst.start_of_year_date is None
                or inst.start_of_year_date.year != current_year
            ):
                res_ytd = _fetch_start_of_year_quote(inst.provider_symbol, current_year)
                if res_ytd is not None:
                    inst.start_of_year_price = Decimal(str(res_ytd[0]))
                    inst.start_of_year_date = res_ytd[1]
                    inst_modified = True

            if inst_modified:
                upsert_instrument(inst)

            return {
                "status": "ok",
                "price": _to_float(q.price),
                "previous_close": _to_float(q.previous_close),
                "analysis_reference_price": _to_float(inst.analysis_reference_price),
                "start_of_year_price": _to_float(inst.start_of_year_price),
                "provider": q.provider,
                "quote_status": q.status.name,
            }
        return {
            "status": "unavailable",
            "detail": f"Yahoo returned no price for {inst.provider_symbol}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _execute_refresh_all() -> dict:
    """Core logic to batch-refresh quotes for all active instruments with Yahoo Finance."""
    with _refresh_lock:
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
        batch_size = get_batch_size()
        runner = BatchRunner(provider=provider, batch_size=batch_size)
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

        result = {
            "status": "ok",
            "updated": updated,
            "failed": failed,
            "total": len(instruments),
        }

        # Auto-resolve analysis reference prices for instruments that have analysis_date but no reference price
        try:
            analysis_res = _execute_resolve_missing_analysis_prices()
            if analysis_res.get("updated", 0) > 0:
                logger.info(
                    "[AutoRefresh] Resolved %d missing analysis reference prices.",
                    analysis_res["updated"],
                )
                result["analysis_prices_updated"] = analysis_res["updated"]
        except Exception as e:
            logger.warning("Could not auto-resolve missing analysis prices during batch refresh: %s", e)

        # Auto-resolve YTD reference prices for active instruments missing start-of-year price for current year
        try:
            ytd_res = _execute_resolve_missing_ytd_prices()
            if ytd_res.get("updated", 0) > 0:
                logger.info(
                    "[AutoRefresh] Resolved %d missing YTD reference prices.",
                    ytd_res["updated"],
                )
                result["ytd_prices_updated"] = ytd_res["updated"]
        except Exception as e:
            logger.warning("Could not auto-resolve missing YTD prices during batch refresh: %s", e)

        _state["last_refresh_at"] = datetime.now().isoformat()
        _state["last_refresh_result"] = result
        return result


@app.post("/api/refresh")
def refresh_all():
    """Batch refresh every instrument's quote from Yahoo Finance."""
    return _execute_refresh_all()


@app.get("/api/config")
def get_config():
    """Return runtime configuration including refresh interval and batch size."""
    return {
        "status": "ok",
        "refresh_interval_seconds": get_refresh_interval(),
        "batch_size": get_batch_size(),
        "last_refresh_at": _state.get("last_refresh_at"),
        "last_refresh_result": _state.get("last_refresh_result"),
    }


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
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

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

    # Automatic safety backup before committing imported data
    try:
        create_automatic_safety_backup(reason="pre_import")
    except Exception as e:
        logger.warning(f"Could not create safety backup before import: {e}")

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
            soy_price = inst_dict.get("start_of_year_price")

            analysis_dt = None
            if inst_dict.get("analysis_date"):
                try:
                    analysis_dt = date.fromisoformat(str(inst_dict["analysis_date"]))
                except ValueError:
                    pass

            soy_dt = None
            if inst_dict.get("start_of_year_date"):
                try:
                    soy_dt = date.fromisoformat(str(inst_dict["start_of_year_date"]))
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
                start_of_year_date=soy_dt,
                start_of_year_price=Decimal(str(soy_price)) if soy_price is not None else None,
                target_price=Decimal(str(tgt_price)) if tgt_price is not None else None,
                comment=inst_dict.get("comment", ""),
                active=inst_dict.get("active", True),
            )
            upsert_instrument(inst)
            committed += 1
        except Exception as e:
            commit_errors.append(f"Error importing '{inst_dict.get('user_ticker', '?')}': {e}")

    return {"status": "ok", "committed": committed, "errors": commit_errors}


# ---- Database management & Backup / Export -------------------------------- #

@app.delete("/api/database")
def wipe_db():
    """Wipe all data from the database (instruments + quotes)."""
    try:
        create_automatic_safety_backup(reason="pre_wipe")
    except Exception as e:
        logger.warning(f"Could not create safety backup before wipe: {e}")
    wipe_database()
    return {"status": "ok", "detail": "Database wiped"}


@app.get("/api/export/csv")
def export_csv():
    """Export the complete watchlist to CSV format."""
    csv_content = export_to_csv()
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfoliomaster_export_{today_str}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/excel")
def export_excel():
    """Export the complete watchlist to Excel (.xlsx) format."""
    excel_bytes = export_to_excel()
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfoliomaster_export_{today_str}.xlsx"
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/json")
def export_json():
    """Export the complete watchlist to versioned JSON schema dump."""
    json_str = export_to_json()
    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"portfoliomaster_backup_{today_str}.json"
    return Response(
        content=json_str,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/backup/download")
def download_backup():
    """Download an atomic, thread-safe SQLite .db file snapshot."""
    today_str = datetime.now().strftime("%Y-%m-%d")
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


@app.post("/api/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    """
    Accept an uploaded .db or .json backup file, validate it,
    create an automatic safety backup of current DB, restore data,
    and return a summary of restored instruments.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No se ha proporcionado ningún archivo")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="El archivo subido está vacío")

    lower_name = file.filename.lower()

    if lower_name.endswith(".json"):
        try:
            text = contents.decode("utf-8")
            result = restore_from_json(text)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error restaurando archivo JSON: {e}")

    elif lower_name.endswith((".db", ".sqlite", ".sqlite3")):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        try:
            is_valid, err = validate_sqlite_backup(tmp_path)
            if not is_valid:
                raise HTTPException(status_code=400, detail=err or "Archivo SQLite corrupto o inválido")
            result = restore_sqlite_backup(tmp_path)
            return result
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al restaurar la base de datos: {e}")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    else:
        raise HTTPException(
            status_code=400,
            detail="Formato de archivo no soportado. Debe ser un archivo .db (SQLite) o .json.",
        )


@app.get("/api/backup/list")
def list_backups():
    """List available local automatic backups in backups/."""
    backups = list_automatic_backups()
    return {"status": "ok", "backups": backups, "count": len(backups)}


@app.post("/api/backup/restore/{filename}")
def restore_local_backup_endpoint(filename: str):
    """Restore database from a local automatic backup file in backups/."""
    try:
        result = restore_automatic_backup(filename)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al restaurar la copia de seguridad: {e}")
