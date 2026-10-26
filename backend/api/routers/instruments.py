"""Instruments CRUD and metadata resolution router for watchlistTracker (WT)."""

from __future__ import annotations

import logging
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
import pandas as pd
import warnings
import yfinance as yf

from portfoliomaster.core.config import get_yahoo_suffix
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db.repository import (
    delete_instrument,
    get_all_instruments,
    get_instrument_by_ticker,
    get_quote_by_instrument_id,
    update_instrument_by_id,
    upsert_instrument,
    upsert_quote,
)
from portfoliomaster.ingest.normalizer import normalize
from portfoliomaster.providers.yahoo_adapter import (
    YahooAdapter,
    _create_ticker,
    resolve_company_name,
)
from ..common import (
    _instrument_to_dict,
    _quote_to_dict,
    _to_float,
    get_current_user_id,
    is_multi_tenant_db,
)
from ..schemas import InstrumentCreate, InstrumentUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def _fetch_start_of_year_quote(
    provider_symbol: str, year: Optional[int] = None
) -> Optional[tuple[float, date]]:
    """Fetch closing price and trading date for the beginning of the given (or current) year."""
    y = year or date.today().year
    target_date = date(y, 1, 1)
    if not provider_symbol:
        return None
    try:
        t = _create_ticker(provider_symbol)
        start_str = target_date.isoformat()
        end_str = (target_date + timedelta(days=10)).isoformat()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
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
    """Fetch closing price and trading date on or before target_date with resilient lookback.
    
    CRITICAL FIX (Bug 2): Eliminates false historical price fallback!
    Only allows fallback to fast_info if target_date is today or within the last 5 days.
    """
    if not provider_symbol or not target_date:
        return None
    try:
        # Special case: Start of Year (Jan 1)
        if target_date.month == 1 and target_date.day == 1:
            return _fetch_start_of_year_quote(provider_symbol, target_date.year)

        t = _create_ticker(provider_symbol)

        # 1. Historical lookback window
        start_str = (target_date - timedelta(days=window_days)).isoformat()
        end_str = (target_date + timedelta(days=1)).isoformat()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            hist = t.history(start=start_str, end=end_str)

        if not hist.empty and "Close" in hist:
            valid_rows = []
            for idx, row in hist.iterrows():
                row_dt = idx.date() if hasattr(idx, "date") else idx.to_pydatetime().date()
                val = row["Close"]
                if row_dt <= target_date and pd.notna(val) and float(val) > 0:
                    valid_rows.append((float(val), row_dt))

            if valid_rows:
                price, actual_dt = valid_rows[-1]
                return round(price, 4), actual_dt

        # 2. Resilient fallback: ONLY for today / recent days within 5 days!
        days_from_today = (date.today() - target_date).days
        if 0 <= days_from_today <= 5:
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


def _get_yahoo_adapter() -> YahooAdapter:
    import sys
    main_mod = sys.modules.get("backend.api.main")
    if main_mod and hasattr(main_mod, "YahooAdapter"):
        cls_or_fn = getattr(main_mod, "YahooAdapter")
        try:
            return cls_or_fn()
        except TypeError:
            return cls_or_fn
    return YahooAdapter()


@router.get("")
def list_instruments(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """All active instruments (for dropdowns / selection)."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            instruments = repo.get_instruments(active_only=True)
            return {
                "instruments": [_instrument_to_dict(inst) for inst in instruments],
                "count": len(instruments),
            }

    instruments = get_all_instruments(include_inactive=False)
    return {
        "instruments": [_instrument_to_dict(inst) for inst in instruments],
        "count": len(instruments),
    }


@router.get("/check-yahoo")
def check_yahoo_ticker(
    ticker: str,
    currency: Optional[str] = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Check whether a ticker exists on Yahoo Finance and resolve its exchange/name."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker query parameter is required")

    curr = (currency or "").strip().upper()
    norm_ticker, detected_exchange = normalize(ticker.strip(), curr)
    suffix = get_yahoo_suffix(ticker.strip(), detected_exchange, curr)
    if suffix and not norm_ticker.upper().endswith(suffix.upper()):
        symbol = f"{norm_ticker}{suffix}"
    else:
        symbol = norm_ticker
    exchange_val = detected_exchange.value if isinstance(detected_exchange, Exchange) else str(detected_exchange)

    result = {
        "ticker": ticker.strip(),
        "provider_symbol": symbol,
        "exchange": exchange_val,
        "valid": False,
        "price": None,
        "company_name": None,
        "currency": curr or "USD",
        "error": None,
    }

    try:
        t = _create_ticker(symbol)
        price = None
        company_name = resolve_company_name(symbol, t)

        fi = getattr(t, "fast_info", None)
        if fi:
            md_fn = getattr(fi, "_get_exchange_metadata", None)
            if callable(md_fn):
                try:
                    meta = md_fn()
                    if isinstance(meta, dict):
                        if not company_name:
                            company_name = meta.get("longName") or meta.get("shortName")
                        if price is None:
                            raw_p = meta.get("regularMarketPrice") or meta.get("fulldayPrice")
                            if raw_p is not None and not math.isnan(float(raw_p)) and float(raw_p) > 0:
                                price = round(float(raw_p), 4)
                        if not result.get("currency") and meta.get("currency"):
                            result["currency"] = str(meta["currency"]).upper()
                except Exception:
                    pass

            try:
                lp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
                if lp is not None and not math.isnan(float(lp)) and float(lp) > 0:
                    price = round(float(lp), 4)
                if price is None:
                    pc = getattr(fi, "previous_close", None) or getattr(fi, "regularMarketPreviousClose", None)
                    if pc is not None and not math.isnan(float(pc)) and float(pc) > 0:
                        price = round(float(pc), 4)
                curr = getattr(fi, "currency", None)
                if curr:
                    result["currency"] = str(curr).upper()
            except Exception:
                pass

        if not company_name:
            company_name = resolve_company_name(symbol, t)

        if price is None:
            try:
                hist = t.history(period="5d")
                if not hist.empty and "Close" in hist:
                    series = hist["Close"].dropna()
                    if not series.empty:
                        last_val = series.iloc[-1]
                        if float(last_val) > 0:
                            price = round(float(last_val), 4)
            except Exception:
                pass

        if price is not None and price > 0:
            result["status"] = "ok"
            result["valid"] = True
            result["available"] = True
            result["price"] = price
            result["company_name"] = company_name or ticker.strip()
        else:
            result["status"] = "ok"
            result["valid"] = False
            result["available"] = False
            result["error"] = f"Symbol '{symbol}' was contacted on Yahoo Finance, but no recent price could be confirmed."

    except Exception as e:
        result["status"] = "error"
        result["valid"] = False
        result["available"] = False
        result["error"] = f"Network or Yahoo Finance error: {e}"

    return result


@router.get("/{ticker}")
def get_instrument(
    ticker: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Single instrument with its quote."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
            inst_dict = _instrument_to_dict(inst)
            quote_dict = _quote_to_dict(inst.quote) if inst.quote else None
            return {
                **inst_dict,
                "quote": quote_dict,
                "instrument": inst_dict,
            }

    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
    result = _instrument_to_dict(inst)
    quote = get_quote_by_instrument_id(inst.id) if inst.id else None
    result["quote"] = _quote_to_dict(quote) if quote else None
    result["instrument"] = _instrument_to_dict(inst)
    return result


def _normalize_currency(curr: Optional[str], default_exchange: Optional[Exchange | str] = None) -> str:
    """Normalize currency, translating AUTO, empty, or whitespace into detected or default currency.
    
    Guarantees 'AUTO' is never persisted to the database.
    """
    if not curr:
        raw = ""
    else:
        raw = curr.strip().upper()
    if raw == "AUTO" or not raw:
        if default_exchange:
            exch_str = default_exchange.value if isinstance(default_exchange, Exchange) else str(default_exchange).upper()
            if exch_str in ("SPAIN", "BME", "IBEX", "PARIS", "FRANKFURT", "AMSTERDAM", "MILAN"):
                return "EUR"
            elif exch_str in ("LONDON", "LSE"):
                return "GBP"
            elif exch_str in ("SWISS", "SIX"):
                return "CHF"
            elif exch_str in ("TOKYO", "TSE"):
                return "JPY"
        return "USD"
    return raw


@router.post("", status_code=201)
def create_instrument_endpoint(
    data: InstrumentCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Add a new instrument to the watchlist."""
    ticker = data.user_ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="user_ticker cannot be empty")

    curr = (data.currency or "").strip().upper()
    if curr == "AUTO":
        curr = ""

    norm_ticker, detected_exchange = normalize(ticker, curr)

    if not data.exchange or data.exchange.upper() == "AUTO":
        exchange = detected_exchange
    else:
        try:
            exchange = Exchange(data.exchange.upper())
        except ValueError:
            exchange = detected_exchange

    final_currency = _normalize_currency(data.currency, exchange)

    suffix = get_yahoo_suffix(ticker, exchange, final_currency)
    if suffix and not norm_ticker.upper().endswith(suffix.upper()):
        provider_symbol = f"{norm_ticker}{suffix}"
    else:
        provider_symbol = norm_ticker

    company_name = data.company_name.strip()
    if not company_name and data.fetch_yahoo:
        resolved = resolve_company_name(provider_symbol)
        if resolved:
            company_name = resolved
    if not company_name:
        company_name = ticker

    analysis_dt = None
    if data.analysis_date and data.analysis_date.strip():
        try:
            analysis_dt = date.fromisoformat(data.analysis_date.strip())
        except ValueError:
            pass

    soy_dt = None
    if data.start_of_year_date and data.start_of_year_date.strip():
        try:
            soy_dt = date.fromisoformat(data.start_of_year_date.strip())
        except ValueError:
            pass

    analysis_price_dec = (
        Decimal(str(data.analysis_reference_price))
        if data.analysis_reference_price is not None and data.analysis_reference_price > 0
        else None
    )
    soy_price_dec = (
        Decimal(str(data.start_of_year_price))
        if data.start_of_year_price is not None and data.start_of_year_price > 0
        else None
    )
    target_price_dec = (
        Decimal(str(data.target_price))
        if data.target_price is not None and data.target_price > 0
        else None
    )

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository
        from portfoliomaster.db.schema import MarketQuote

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            existing = repo.get_instrument_by_ticker(ticker)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Instrument with ticker '{ticker}' already exists in database.",
                )

            inst_created = repo.create_instrument(
                user_ticker=ticker,
                provider_symbol=provider_symbol,
                exchange=exchange.value if hasattr(exchange, "value") else str(exchange),
                currency=final_currency,
                company_name=company_name,
                analysis_date=analysis_dt,
                analysis_reference_price=analysis_price_dec,
                start_of_year_date=soy_dt,
                start_of_year_price=soy_price_dec,
                target_price=target_price_dec,
                comment=data.comment.strip(),
                active=True,
            )

            quote_info = None
            if data.manual_price is not None and data.manual_price > 0:
                mq = session.get(MarketQuote, provider_symbol)
                if not mq:
                    mq = MarketQuote(
                        provider_symbol=provider_symbol,
                        exchange=inst_created.exchange,
                        currency=inst_created.currency,
                        company_name=company_name,
                    )
                    session.add(mq)
                mq.price = Decimal(str(data.manual_price))
                if data.manual_previous_close and data.manual_previous_close > 0:
                    mq.previous_close = Decimal(str(data.manual_previous_close))
                mq.status = "FRESH"
                mq.last_valid_fetched_at = datetime.now(timezone.utc)
                quote_info = {"source": "manual", "price": data.manual_price}
            elif data.fetch_yahoo:
                from .refresh import _get_yahoo_adapter
                adapter = _get_yahoo_adapter()
                quotes = adapter.fetch([provider_symbol])
                if provider_symbol in quotes:
                    q_fetched = quotes[provider_symbol]
                    mq = session.get(MarketQuote, provider_symbol)
                    if not mq:
                        mq = MarketQuote(
                            provider_symbol=provider_symbol,
                            exchange=inst_created.exchange,
                            currency=inst_created.currency,
                            company_name=company_name,
                        )
                        session.add(mq)
                    mq.price = q_fetched.price
                    mq.previous_close = q_fetched.previous_close
                    mq.status = q_fetched.status.name if hasattr(q_fetched.status, "name") else str(q_fetched.status)
                    mq.last_valid_fetched_at = datetime.now(timezone.utc)
                    quote_info = {"source": "yahoo", "price": _to_float(q_fetched.price)}

            if data.fetch_yahoo and not inst_created.start_of_year_price:
                res_ytd = _fetch_start_of_year_quote(provider_symbol)
                if res_ytd:
                    p_ytd, dt_ytd = res_ytd
                    inst_created.start_of_year_price = Decimal(str(p_ytd))
                    inst_created.start_of_year_date = dt_ytd

            session.commit()
            return {"status": "ok", "instrument": _instrument_to_dict(inst_created), "quote": quote_info}

    existing = get_instrument_by_ticker(ticker)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Instrument with ticker '{ticker}' already exists in database.",
        )

    inst = Instrument(
        user_ticker=ticker,
        provider_symbol=provider_symbol,
        exchange=exchange,
        currency=final_currency,
        company_name=company_name,
        analysis_date=analysis_dt,
        analysis_reference_price=analysis_price_dec,
        start_of_year_date=soy_dt,
        start_of_year_price=soy_price_dec,
        target_price=target_price_dec,
        comment=data.comment.strip(),
        active=True,
    )
    upsert_instrument(inst)

    persisted = get_instrument_by_ticker(ticker)
    if not persisted or not persisted.id:
        raise HTTPException(status_code=500, detail="Failed to persist instrument")

    # Fetch initial quote or manual price
    quote_info = None
    if data.manual_price is not None and data.manual_price > 0:
        q = Quote(
            instrument_id=persisted.id,
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
    elif data.fetch_yahoo:
        adapter = _get_yahoo_adapter()
        quotes = adapter.fetch([provider_symbol])
        if provider_symbol in quotes:
            q = quotes[provider_symbol]
            q.instrument_id = persisted.id
            upsert_quote(q)
            quote_info = {"source": "yahoo", "price": _to_float(q.price)}
        else:
            quote_info = {"source": "yahoo", "price": None, "note": f"Yahoo did not return a price for '{provider_symbol}'"}

    # Resolve missing analysis price if date provided
    if analysis_dt and not analysis_price_dec and data.fetch_yahoo:
        res = _fetch_historical_quote_and_date(provider_symbol, analysis_dt, window_days=10)
        if res:
            p_val, actual_dt = res
            persisted.analysis_reference_price = Decimal(str(p_val))
            persisted.analysis_date = actual_dt
            update_instrument_by_id(persisted)

    # Resolve start of year price
    if not soy_price_dec and data.fetch_yahoo:
        ref_year = analysis_dt.year if analysis_dt else date.today().year
        res_ytd = _fetch_start_of_year_quote(provider_symbol, ref_year)
        if res_ytd:
            p_ytd, dt_ytd = res_ytd
            persisted.start_of_year_price = Decimal(str(p_ytd))
            persisted.start_of_year_date = dt_ytd
            update_instrument_by_id(persisted)

    final_inst = get_instrument_by_ticker(ticker)
    return {
        "status": "ok",
        "instrument": _instrument_to_dict(final_inst or persisted),
        "quote": quote_info,
    }


@router.put("/{ticker}")
def update_instrument_endpoint(
    ticker: str,
    data: InstrumentUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Update instrument fields with strict tristate PATCH semantics (Bug 6 fix).
    
    Fields omitted in the JSON payload are preserved.
    Fields explicitly sent as null are cleared to NULL in the database.
    """
    fields_set = getattr(data, "model_fields_set", set())

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository
        from portfoliomaster.db.schema import MarketQuote

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

            ticker_changed = False
            new_ticker_val = None
            if "new_ticker" in fields_set and data.new_ticker and data.new_ticker.strip().upper() != inst.user_ticker:
                new_t = data.new_ticker.strip().upper()
                existing = repo.get_instrument_by_ticker(new_t)
                if existing and existing.id != inst.id:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot rename to '{new_t}': another instrument already uses that ticker.",
                    )
                new_ticker_val = new_t
                ticker_changed = True

            # Calculate provider_symbol if ticker or exchange or currency changed
            provider_symbol_val = inst.provider_symbol
            effective_ticker = new_ticker_val if ticker_changed else inst.user_ticker
            effective_curr = (
                _normalize_currency(data.currency, inst.exchange)
                if ("currency" in fields_set and data.currency is not None)
                else (inst.currency or "USD")
            )

            norm_ticker, detected_exchange = normalize(effective_ticker, effective_curr)
            if "exchange" in fields_set and data.exchange is not None and data.exchange.strip() and data.exchange.strip().upper() != "AUTO":
                try:
                    eff_exchange = Exchange(data.exchange.strip().upper()).value
                except ValueError:
                    eff_exchange = detected_exchange.value if hasattr(detected_exchange, "value") else str(detected_exchange)
            else:
                eff_exchange = inst.exchange

            suffix = get_yahoo_suffix(effective_ticker, eff_exchange, effective_curr)
            if suffix and not norm_ticker.upper().endswith(suffix.upper()):
                provider_symbol_val = f"{norm_ticker}{suffix}"
            else:
                provider_symbol_val = norm_ticker

            # Parse reference prices and dates
            an_dt = None
            if "analysis_date" in fields_set:
                if data.analysis_date and data.analysis_date.strip():
                    try:
                        an_dt = date.fromisoformat(data.analysis_date.strip())
                    except ValueError:
                        pass

            an_pr = None
            if "analysis_reference_price" in fields_set and data.analysis_reference_price is not None and data.analysis_reference_price > 0:
                an_pr = Decimal(str(data.analysis_reference_price))

            soy_dt = None
            if "start_of_year_date" in fields_set:
                if data.start_of_year_date and data.start_of_year_date.strip():
                    try:
                        soy_dt = date.fromisoformat(data.start_of_year_date.strip())
                    except ValueError:
                        pass

            soy_pr = None
            if "start_of_year_price" in fields_set and data.start_of_year_price is not None and data.start_of_year_price > 0:
                soy_pr = Decimal(str(data.start_of_year_price))

            tgt_pr = None
            if "target_price" in fields_set and data.target_price is not None and data.target_price > 0:
                tgt_pr = Decimal(str(data.target_price))

            updated = repo.update_instrument(
                ticker=ticker,
                fields_set=fields_set,
                new_ticker=new_ticker_val,
                provider_symbol=provider_symbol_val,
                exchange=eff_exchange if ("exchange" in fields_set or ticker_changed) else None,
                currency=effective_curr if "currency" in fields_set else None,
                company_name=data.company_name.strip() if "company_name" in fields_set and data.company_name else None,
                analysis_date=an_dt,
                analysis_reference_price=an_pr,
                start_of_year_date=soy_dt,
                start_of_year_price=soy_pr,
                target_price=tgt_pr,
                comment=data.comment.strip() if "comment" in fields_set and data.comment is not None else None,
                active=data.active if "active" in fields_set else None,
            )

            # Ensure market quote placeholder exists for provider_symbol
            if provider_symbol_val:
                mq = session.get(MarketQuote, provider_symbol_val)
                if not mq:
                    mq = MarketQuote(
                        provider_symbol=provider_symbol_val,
                        exchange=updated.exchange,
                        currency=updated.currency,
                        company_name=updated.company_name,
                    )
                    session.add(mq)

            session.commit()
            return {
                "status": "ok",
                "instrument": _instrument_to_dict(updated),
            }

    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    fields_set = getattr(data, "model_fields_set", set())

    ticker_changed = False
    if "new_ticker" in fields_set and data.new_ticker and data.new_ticker.strip().upper() != inst.user_ticker:
        new_t = data.new_ticker.strip().upper()
        existing = get_instrument_by_ticker(new_t)
        if existing and existing.id != inst.id:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot rename to '{new_t}': another instrument already uses that ticker.",
            )
        inst.user_ticker = new_t
        ticker_changed = True

    if "currency" in fields_set and data.currency is not None:
        inst.currency = _normalize_currency(data.currency, inst.exchange)

    if ticker_changed or "exchange" in fields_set:
        curr_for_norm = inst.currency or ""
        norm_ticker, detected_exchange = normalize(inst.user_ticker, curr_for_norm)

        if "exchange" in fields_set and data.exchange is not None and data.exchange.strip() and data.exchange.strip().upper() != "AUTO":
            try:
                inst.exchange = Exchange(data.exchange.strip().upper())
            except ValueError:
                inst.exchange = detected_exchange
        elif detected_exchange != Exchange.UNKNOWN:
            inst.exchange = detected_exchange

        suffix = get_yahoo_suffix(inst.user_ticker, inst.exchange, curr_for_norm)
        if suffix and not norm_ticker.upper().endswith(suffix.upper()):
            inst.provider_symbol = f"{norm_ticker}{suffix}"
        else:
            inst.provider_symbol = norm_ticker

    if "company_name" in fields_set and data.company_name is not None:
        if data.company_name.strip():
            inst.company_name = data.company_name.strip()
        else:
            inst.company_name = inst.user_ticker

    # CRITICAL FIX (Bug 6): Tristate PATCH semantics for nullable fields
    if "target_price" in fields_set:
        if data.target_price is not None and data.target_price > 0:
            inst.target_price = Decimal(str(data.target_price))
        else:
            inst.target_price = None

    if "analysis_reference_price" in fields_set:
        if data.analysis_reference_price is not None and data.analysis_reference_price > 0:
            inst.analysis_reference_price = Decimal(str(data.analysis_reference_price))
        else:
            inst.analysis_reference_price = None

    if "analysis_date" in fields_set:
        if data.analysis_date and data.analysis_date.strip():
            try:
                inst.analysis_date = date.fromisoformat(data.analysis_date.strip())
            except ValueError:
                inst.analysis_date = None
        else:
            inst.analysis_date = None

    if "start_of_year_price" in fields_set:
        if data.start_of_year_price is not None and data.start_of_year_price > 0:
            inst.start_of_year_price = Decimal(str(data.start_of_year_price))
        else:
            inst.start_of_year_price = None

    if "start_of_year_date" in fields_set:
        if data.start_of_year_date and data.start_of_year_date.strip():
            try:
                inst.start_of_year_date = date.fromisoformat(data.start_of_year_date.strip())
            except ValueError:
                inst.start_of_year_date = None
        else:
            inst.start_of_year_date = None

    if "comment" in fields_set:
        inst.comment = (data.comment or "").strip()

    if "active" in fields_set and data.active is not None:
        inst.active = bool(data.active)

    update_instrument_by_id(inst)

    # Quote update
    if "latest_price" in fields_set and data.latest_price is not None and data.latest_price > 0 and inst.id:
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
            adapter = _get_yahoo_adapter()
            quotes = adapter.fetch([inst.provider_symbol])
            if inst.provider_symbol in quotes and quotes[inst.provider_symbol].is_valid():
                q = quotes[inst.provider_symbol]
                q.instrument_id = inst.id
                upsert_quote(q)
        except Exception as e:
            logger.debug(f"Could not fetch quote on rename: {e}")

    return {"status": "ok", "instrument": _instrument_to_dict(inst)}


@router.delete("/{ticker}")
def delete_instrument_endpoint(
    ticker: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Delete an instrument and its associated quote from the database."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            deleted = repo.delete_instrument(ticker)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
            return {"status": "deleted", "deleted": ticker, "ticker": ticker}

    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
    delete_instrument(ticker)
    return {"status": "deleted", "deleted": ticker, "ticker": ticker}


@router.post("/{ticker}/fetch-analysis-price")
def fetch_analysis_price_endpoint(
    ticker: str,
    target_date: Optional[str] = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Fetch historical quote from Yahoo Finance for instrument's analysis_date."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

            parsed_target_date: Optional[date] = None
            if target_date and target_date.strip():
                try:
                    parsed_target_date = date.fromisoformat(target_date.strip())
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid date format '{target_date}'. Expected YYYY-MM-DD.")
            elif inst.analysis_date:
                parsed_target_date = inst.analysis_date
            else:
                raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no analysis_date configured.")

            if not inst.provider_symbol:
                raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol resolved.")

            res = _fetch_historical_quote_and_date(inst.provider_symbol, parsed_target_date, window_days=10)
            if not res:
                raise HTTPException(
                    status_code=404,
                    detail=f"No market quote found on Yahoo Finance for {inst.provider_symbol} on or near {parsed_target_date}.",
                )

            price, actual_dt = res
            inst.analysis_reference_price = Decimal(str(price))
            inst.analysis_date = actual_dt
            session.commit()

            return {
                "status": "ok",
                "ticker": inst.user_ticker,
                "analysis_date": actual_dt.isoformat(),
                "analysis_reference_price": price,
            }

    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    parsed_target_date: Optional[date] = None
    if target_date and target_date.strip():
        try:
            parsed_target_date = date.fromisoformat(target_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date format '{target_date}'. Expected YYYY-MM-DD.")
    elif inst.analysis_date:
        parsed_target_date = inst.analysis_date
    else:
        raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no analysis_date configured.")

    if not inst.provider_symbol:
        raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol resolved.")

    res = _fetch_historical_quote_and_date(inst.provider_symbol, parsed_target_date, window_days=10)
    if not res:
        raise HTTPException(
            status_code=404,
            detail=f"No market quote found on Yahoo Finance for {inst.provider_symbol} on or near {parsed_target_date}.",
        )

    price, actual_dt = res
    inst.analysis_reference_price = Decimal(str(price))
    inst.analysis_date = actual_dt
    update_instrument_by_id(inst)

    return {
        "status": "ok",
        "ticker": inst.user_ticker,
        "analysis_date": actual_dt.isoformat(),
        "analysis_reference_price": price,
    }


@router.post("/{ticker}/fetch-ytd-price")
def fetch_ytd_price_endpoint(
    ticker: str,
    target_year: Optional[int] = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Fetch start of year quote from Yahoo Finance for instrument for the given year."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

            y = target_year or (inst.start_of_year_date.year if inst.start_of_year_date else date.today().year)
            if not inst.provider_symbol:
                raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol resolved.")

            res = _fetch_start_of_year_quote(inst.provider_symbol, y)
            if not res:
                raise HTTPException(
                    status_code=404,
                    detail=f"No start-of-year quote found on Yahoo Finance for {inst.provider_symbol} in year {y}.",
                )

            price, actual_dt = res
            inst.start_of_year_price = Decimal(str(price))
            inst.start_of_year_date = actual_dt
            session.commit()

            return {
                "status": "ok",
                "ticker": inst.user_ticker,
                "start_of_year_date": actual_dt.isoformat(),
                "start_of_year_price": price,
            }

    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    y = target_year or (inst.start_of_year_date.year if inst.start_of_year_date else date.today().year)
    if not inst.provider_symbol:
        raise HTTPException(status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol resolved.")

    res = _fetch_start_of_year_quote(inst.provider_symbol, y)
    if not res:
        raise HTTPException(
            status_code=404,
            detail=f"No start-of-year quote found on Yahoo Finance for {inst.provider_symbol} in year {y}.",
        )

    price, actual_dt = res
    inst.start_of_year_price = Decimal(str(price))
    inst.start_of_year_date = actual_dt
    update_instrument_by_id(inst)

    return {
        "status": "ok",
        "ticker": inst.user_ticker,
        "start_of_year_date": actual_dt.isoformat(),
        "start_of_year_price": price,
    }


def _resolve_price_for_instrument(
    inst: Any,
    is_multi_tenant: bool,
    fetch_fn: Callable[[], Optional[tuple[float, date]]],
    target_attr_price: str,
    target_attr_date: str,
) -> bool:
    """Helper to resolve and persist missing price/date on an instrument object."""
    if not inst.provider_symbol:
        return False
    try:
        res = fetch_fn()
        if res:
            p_val, actual_dt = res
            setattr(inst, target_attr_price, Decimal(str(p_val)))
            setattr(inst, target_attr_date, actual_dt)
            if not is_multi_tenant:
                update_instrument_by_id(inst)
            return True
    except Exception as e:
        logger.debug(f"Error resolving price for {getattr(inst, 'user_ticker', '?')}: {e}")
    return False


@router.post("/resolve-missing-analysis-prices")
def resolve_missing_analysis_prices(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Batch resolve missing analysis reference prices for instruments having analysis_date."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            instruments = repo.get_instruments(active_only=True)
            candidates = [i for i in instruments if i.analysis_date and not i.analysis_reference_price]
            updated, failed = 0, 0
            for inst in candidates:
                if not inst.analysis_date:
                    failed += 1
                    continue
                ok = _resolve_price_for_instrument(
                    inst,
                    is_multi_tenant=True,
                    fetch_fn=lambda s=inst.provider_symbol, d=inst.analysis_date: _fetch_historical_quote_and_date(s, d, window_days=10),
                    target_attr_price="analysis_reference_price",
                    target_attr_date="analysis_date",
                )
                if ok:
                    updated += 1
                else:
                    failed += 1
            session.commit()
            return {
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "skipped": len(instruments) - len(candidates),
                "total": len(instruments),
            }

    active_instruments = get_all_instruments(include_inactive=False)
    candidates = [i for i in active_instruments if i.analysis_date and not i.analysis_reference_price]
    updated, failed = 0, 0
    for inst in candidates:
        if not inst.analysis_date:
            failed += 1
            continue
        ok = _resolve_price_for_instrument(
            inst,
            is_multi_tenant=False,
            fetch_fn=lambda s=inst.provider_symbol, d=inst.analysis_date: _fetch_historical_quote_and_date(s, d, window_days=10),
            target_attr_price="analysis_reference_price",
            target_attr_date="analysis_date",
        )
        if ok:
            updated += 1
        else:
            failed += 1

    return {
        "status": "ok",
        "updated": updated,
        "failed": failed,
        "skipped": len(active_instruments) - len(candidates),
        "total": len(active_instruments),
    }


@router.post("/resolve-missing-ytd-prices")
def resolve_missing_ytd_prices(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Batch resolve missing start-of-year prices for instruments for the current year."""
    current_year = date.today().year

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            instruments = repo.get_instruments(active_only=True)
            candidates = [i for i in instruments if not i.start_of_year_price]
            updated, failed = 0, 0
            for inst in candidates:
                ok = _resolve_price_for_instrument(
                    inst,
                    is_multi_tenant=True,
                    fetch_fn=lambda s=inst.provider_symbol, y=current_year: _fetch_start_of_year_quote(s, y),
                    target_attr_price="start_of_year_price",
                    target_attr_date="start_of_year_date",
                )
                if ok:
                    updated += 1
                else:
                    failed += 1
            session.commit()
            return {
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "skipped": len(instruments) - len(candidates),
                "total": len(instruments),
            }

    active_instruments = get_all_instruments(include_inactive=False)
    candidates = [i for i in active_instruments if not i.start_of_year_price]
    updated, failed = 0, 0
    for inst in candidates:
        ok = _resolve_price_for_instrument(
            inst,
            is_multi_tenant=False,
            fetch_fn=lambda s=inst.provider_symbol, y=current_year: _fetch_start_of_year_quote(s, y),
            target_attr_price="start_of_year_price",
            target_attr_date="start_of_year_date",
        )
        if ok:
            updated += 1
        else:
            failed += 1

    return {
        "status": "ok",
        "updated": updated,
        "failed": failed,
        "skipped": len(active_instruments) - len(candidates),
        "total": len(active_instruments),
    }
