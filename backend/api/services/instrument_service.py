"""Domain service for instrument CRUD, metadata normalization, and historical price resolution."""

from __future__ import annotations

import concurrent.futures
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Optional

from fastapi import HTTPException

from portfoliomaster.core.config import get_yahoo_suffix
from portfoliomaster.core.models import Exchange
from portfoliomaster.core.parsing import (
    parse_optional_iso_date as _core_parse_optional_iso_date,
    positive_float as _core_positive_float,
)
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.ingest.normalizer import normalize as _default_normalize
from portfoliomaster.providers.yahoo_adapter import (
    YahooAdapter,
    _create_ticker as _default_create_ticker,
    resolve_company_name as _default_resolve_company_name,
)

from ..common import is_production
from ..schemas import CheckYahooResponse, InstrumentCreate, InstrumentUpdate
from .cache import invalidate_positions_cache

logger = logging.getLogger(__name__)


def parse_optional_iso_date(raw: Optional[str], field_name: str) -> Optional[date]:
    """Parse an optional ISO-8601 date string or raise HTTP 422 on malformed input."""
    try:
        return _core_parse_optional_iso_date(raw, field_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def build_provider_symbol(
    norm_ticker: str, raw_ticker: str, exchange: Exchange | str, currency: str
) -> str:
    """Resolve Yahoo Finance provider_symbol from normalized ticker, exchange, and currency."""
    suffix = get_yahoo_suffix(raw_ticker, exchange, currency)
    if suffix and not norm_ticker.upper().endswith(suffix.upper()):
        return f"{norm_ticker}{suffix}"
    return norm_ticker


def positive_float(value: Any) -> Optional[float]:
    """Return rounded positive float or None when missing/non-positive/NaN."""
    return _core_positive_float(value, ndigits=4)


def normalize_currency(
    curr: Optional[str], default_exchange: Optional[Exchange | str] = None
) -> str:
    """Normalize currency, translating AUTO, empty, or whitespace into detected or default currency."""
    raw = curr.strip().upper() if curr else ""
    if raw == "AUTO" or not raw:
        if default_exchange:
            exch_str = (
                default_exchange.value
                if isinstance(default_exchange, Exchange)
                else str(default_exchange).upper()
            )
            if exch_str in ("SPAIN", "BME", "IBEX", "PARIS", "FRANKFURT", "AMSTERDAM", "MILAN"):
                return "EUR"
            if exch_str in ("LONDON", "LSE"):
                return "GBP"
            if exch_str in ("SWISS", "SIX"):
                return "CHF"
            if exch_str in ("TOKYO", "TSE"):
                return "JPY"
        return "USD"
    return raw


def check_yahoo_ticker_metadata(
    ticker: str,
    currency: Optional[str] = None,
    *,
    normalize_fn: Callable[[str, str], tuple[str, Exchange]] = _default_normalize,
    create_ticker_fn: Callable[[str], Any] = _default_create_ticker,
    resolve_name_fn: Callable[[str, Any], Optional[str]] = _default_resolve_company_name,
) -> CheckYahooResponse:
    """Check whether a ticker exists on Yahoo Finance and resolve its exchange/name."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker query parameter is required")

    clean_ticker = ticker.strip()
    curr = (currency or "").strip().upper()
    norm_ticker, detected_exchange = normalize_fn(clean_ticker, curr)
    symbol = build_provider_symbol(norm_ticker, clean_ticker, detected_exchange, curr)
    exchange_val = (
        detected_exchange.value
        if isinstance(detected_exchange, Exchange)
        else str(detected_exchange)
    )
    resolved_currency = curr or "USD"

    try:
        t = create_ticker_fn(symbol)
        price: Optional[float] = None
        previous_close: Optional[float] = None
        company_name: Optional[str] = None

        fi = getattr(t, "fast_info", None)
        if fi:
            md_fn = getattr(fi, "_get_exchange_metadata", None)
            if callable(md_fn):
                try:
                    meta = md_fn()
                    if isinstance(meta, dict):
                        company_name = meta.get("longName") or meta.get("shortName")
                        price = positive_float(
                            meta.get("regularMarketPrice") or meta.get("fulldayPrice")
                        )
                        previous_close = positive_float(
                            meta.get("regularMarketPreviousClose")
                            or meta.get("chartPreviousClose")
                        )
                        if not curr and meta.get("currency"):
                            resolved_currency = str(meta["currency"]).upper()
                except Exception:
                    pass

            try:
                fi_price = positive_float(
                    getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
                )
                if fi_price is not None:
                    price = fi_price
                fi_prev = positive_float(
                    getattr(fi, "previous_close", None)
                    or getattr(fi, "regularMarketPreviousClose", None)
                )
                if fi_prev is not None:
                    previous_close = fi_prev
                if price is None and previous_close is not None:
                    price = previous_close
                fi_curr = getattr(fi, "currency", None)
                if fi_curr:
                    resolved_currency = str(fi_curr).upper()
            except Exception:
                pass

        if not company_name:
            company_name = resolve_name_fn(symbol, t)

        if price is None:
            try:
                hist = t.history(period="5d")
                if not hist.empty and "Close" in hist:
                    series = hist["Close"].dropna()
                    if not series.empty:
                        price = positive_float(series.iloc[-1])
                        if previous_close is None and len(series) >= 2:
                            previous_close = positive_float(series.iloc[-2])
            except Exception:
                pass

        if price is not None and price > 0:
            return CheckYahooResponse(
                status="ok",
                available=True,
                valid=True,
                ticker=clean_ticker,
                provider_symbol=symbol,
                exchange=exchange_val,
                currency=resolved_currency,
                price=price,
                previous_close=previous_close,
                company_name=company_name or clean_ticker,
                message=None,
                error=None,
            )

        not_found_msg = (
            f"Symbol '{symbol}' was contacted on Yahoo Finance, but no recent price could be confirmed."
        )
        return CheckYahooResponse(
            status="ok",
            available=False,
            valid=False,
            ticker=clean_ticker,
            provider_symbol=symbol,
            exchange=exchange_val,
            currency=resolved_currency,
            price=None,
            previous_close=previous_close,
            company_name=company_name,
            message=not_found_msg,
            error=not_found_msg,
        )

    except Exception as e:
        logger.warning("Yahoo check failed for %s: %s", symbol, e)
        detail = (
            "Failed to query Yahoo Finance."
            if is_production()
            else f"Network or Yahoo Finance error: {e}"
        )
        raise HTTPException(status_code=502, detail=detail) from e


def create_instrument(
    data: InstrumentCreate,
    user_id: uuid.UUID,
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    normalize_fn: Callable[[str, str], tuple[str, Exchange]] = _default_normalize,
    resolve_name_fn: Callable[..., Optional[str]] = _default_resolve_company_name,
    fetch_hist_fn: Optional[Callable[[str, date, int], Optional[tuple[float, date]]]] = None,
    fetch_soy_fn: Optional[Callable[[str, Optional[int]], Optional[tuple[float, date]]]] = None,
) -> dict:
    """Create a watchlist instrument, performing all Yahoo lookups outside DB sessions."""
    ticker = data.user_ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="user_ticker cannot be empty")

    curr = (data.currency or "").strip().upper()
    if curr == "AUTO":
        curr = ""

    norm_ticker, detected_exchange = normalize_fn(ticker, curr)

    if not data.exchange or data.exchange.upper() == "AUTO":
        exchange = detected_exchange
    else:
        try:
            exchange = Exchange(data.exchange.upper())
        except ValueError:
            exchange = detected_exchange

    final_currency = normalize_currency(data.currency, exchange)
    provider_symbol = build_provider_symbol(norm_ticker, ticker, exchange, final_currency)

    analysis_dt = parse_optional_iso_date(data.analysis_date, "analysis_date")
    soy_dt = parse_optional_iso_date(data.start_of_year_date, "start_of_year_date")

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

    # Check existence in a short self-contained read before executing network calls
    if store.instrument_exists(ticker):
        raise HTTPException(
            status_code=400,
            detail=f"Instrument with ticker '{ticker}' already exists in database.",
        )

    company_name = data.company_name.strip()
    if not company_name and data.fetch_yahoo:
        resolved = resolve_name_fn(provider_symbol)
        if resolved:
            company_name = resolved
    if not company_name:
        company_name = ticker

    manual_price = data.manual_price if data.manual_price and data.manual_price > 0 else None
    fetched_quote = None
    hist_lookup = fetch_hist_fn or provider.fetch_historical_quote_and_date
    soy_lookup = fetch_soy_fn or provider.fetch_start_of_year_quote

    if data.fetch_yahoo:
        if manual_price is None:
            fetched_quote = provider.fetch([provider_symbol]).get(provider_symbol)
        if analysis_dt and not analysis_price_dec:
            res_an = hist_lookup(provider_symbol, analysis_dt, 10)
            if res_an:
                analysis_price_dec = Decimal(str(res_an[0]))
                analysis_dt = res_an[1]
        if soy_price_dec is None:
            year_start_quote = (
                soy_lookup(provider_symbol, analysis_dt.year)
                if analysis_dt
                else soy_lookup(provider_symbol)
            )
            if year_start_quote:
                ytd_price, soy_dt = year_start_quote
                soy_price_dec = Decimal(str(ytd_price))

    payload = {
        "user_ticker": ticker,
        "provider_symbol": provider_symbol,
        "exchange": exchange.value if hasattr(exchange, "value") else str(exchange),
        "currency": final_currency,
        "company_name": company_name,
        "analysis_date": analysis_dt,
        "analysis_reference_price": analysis_price_dec,
        "start_of_year_date": soy_dt,
        "start_of_year_price": soy_price_dec,
        "target_price": target_price_dec,
        "comment": data.comment.strip(),
        "active": True,
    }

    try:
        instrument_dict, quote_info = store.create_instrument(
            payload,
            fetched_quote=fetched_quote,
            manual_price=manual_price,
            manual_previous_close=data.manual_previous_close,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not store.supports_sqlite_file_backups and fetched_quote is not None and manual_price is None:
        invalidate_positions_cache()
    else:
        invalidate_positions_cache(user_id)

    return {"status": "ok", "instrument": instrument_dict, "quote": quote_info}


def update_instrument(
    ticker: str,
    data: InstrumentUpdate,
    user_id: uuid.UUID,
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    normalize_fn: Callable[[str, str], tuple[str, Exchange]] = _default_normalize,
) -> dict:
    """Update instrument fields with strict tristate PATCH semantics."""
    snapshot = store.get_instrument_snapshot_for_update(ticker)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    fields_set = set(getattr(data, "model_fields_set", set()))
    current_ticker = str(snapshot["user_ticker"])
    current_exchange = snapshot.get("exchange")
    current_curr = str(snapshot.get("currency") or "USD")
    provider_symbol_val = snapshot.get("provider_symbol")

    ticker_changed = False
    new_ticker_val = None
    if "new_ticker" in fields_set and data.new_ticker and data.new_ticker.strip().upper() != current_ticker:
        new_ticker_val = data.new_ticker.strip().upper()
        ticker_changed = True

    recompute_symbol = ticker_changed or "exchange" in fields_set or "currency" in fields_set
    effective_ticker = new_ticker_val if ticker_changed and new_ticker_val else current_ticker
    effective_curr = (
        normalize_currency(data.currency, current_exchange)
        if ("currency" in fields_set and data.currency is not None)
        else current_curr
    )
    eff_exchange = current_exchange

    if recompute_symbol:
        norm_ticker, detected_exchange = normalize_fn(effective_ticker, effective_curr)
        if (
            "exchange" in fields_set
            and data.exchange is not None
            and data.exchange.strip()
            and data.exchange.strip().upper() != "AUTO"
        ):
            try:
                eff_exchange = Exchange(data.exchange.strip().upper()).value
            except ValueError:
                eff_exchange = (
                    detected_exchange.value
                    if hasattr(detected_exchange, "value")
                    else str(detected_exchange)
                )
        elif "exchange" in fields_set or detected_exchange != Exchange.UNKNOWN:
            eff_exchange = (
                detected_exchange.value
                if hasattr(detected_exchange, "value")
                else str(detected_exchange)
            )
        provider_symbol_val = build_provider_symbol(
            norm_ticker, effective_ticker, eff_exchange, effective_curr
        )

    an_dt = (
        parse_optional_iso_date(data.analysis_date, "analysis_date")
        if "analysis_date" in fields_set
        else None
    )
    an_pr = (
        Decimal(str(data.analysis_reference_price))
        if ("analysis_reference_price" in fields_set and data.analysis_reference_price is not None and data.analysis_reference_price > 0)
        else None
    )
    soy_dt = (
        parse_optional_iso_date(data.start_of_year_date, "start_of_year_date")
        if "start_of_year_date" in fields_set
        else None
    )
    soy_pr = (
        Decimal(str(data.start_of_year_price))
        if ("start_of_year_price" in fields_set and data.start_of_year_price is not None and data.start_of_year_price > 0)
        else None
    )
    tgt_pr = (
        Decimal(str(data.target_price))
        if ("target_price" in fields_set and data.target_price is not None and data.target_price > 0)
        else None
    )

    repo_fields_set = set(fields_set)
    if recompute_symbol:
        repo_fields_set.add("provider_symbol")
        if eff_exchange is not None:
            repo_fields_set.add("exchange")

    rename_quote = None
    if (
        store.supports_sqlite_file_backups
        and ticker_changed
        and provider_symbol_val
        and not ("latest_price" in fields_set and data.latest_price is not None and data.latest_price > 0)
    ):
        try:
            quotes = provider.fetch([provider_symbol_val])
            q = quotes.get(provider_symbol_val)
            if q and q.is_valid():
                rename_quote = q
        except Exception as e:
            logger.debug("Could not fetch quote on rename: %s", e)

    clean_company_name = (
        (data.company_name.strip() or None)
        if ("company_name" in fields_set and data.company_name is not None)
        else None
    )

    updates_payload: dict[str, Any] = {
        "new_ticker": new_ticker_val,
        "provider_symbol": provider_symbol_val,
        "exchange": eff_exchange if recompute_symbol else None,
        "currency": effective_curr if "currency" in fields_set else None,
        "company_name": clean_company_name,
        "analysis_date": an_dt,
        "analysis_reference_price": an_pr,
        "start_of_year_date": soy_dt,
        "start_of_year_price": soy_pr,
        "target_price": tgt_pr,
        "comment": data.comment.strip() if "comment" in fields_set and data.comment is not None else None,
        "active": data.active if "active" in fields_set else None,
        "latest_price": data.latest_price if "latest_price" in fields_set else None,
        "previous_close": data.previous_close if "previous_close" in fields_set else None,
        "_rename_quote": rename_quote,
    }

    try:
        updated_dict = store.update_instrument(ticker, repo_fields_set, updates_payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    invalidate_positions_cache(user_id)
    return {"status": "ok", "instrument": updated_dict}


def delete_instrument(
    ticker: str,
    user_id: uuid.UUID,
    store: PortfolioStore,
) -> dict:
    """Delete an instrument and invalidate tenant cache after commit."""
    deleted = store.delete_instrument(ticker)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
    invalidate_positions_cache(user_id)
    return {"status": "deleted", "deleted": ticker, "ticker": ticker}


def fetch_analysis_price(
    ticker: str,
    target_date: Optional[str],
    user_id: uuid.UUID,
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    fetch_hist_fn: Optional[Callable[[str, date, int], Optional[tuple[float, date]]]] = None,
) -> dict:
    """Resolve and persist an instrument's analysis reference price using short DB sessions."""
    target = store.get_analysis_lookup_target(ticker)
    if not target:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    target_id, inst_ticker, inst_analysis_date, provider_symbol = target
    parsed_target_date: Optional[date] = None
    if target_date and target_date.strip():
        try:
            parsed_target_date = date.fromisoformat(target_date.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format '{target_date}'. Expected YYYY-MM-DD.",
            ) from exc
    elif inst_analysis_date:
        parsed_target_date = inst_analysis_date
    else:
        raise HTTPException(
            status_code=400, detail=f"Instrument '{ticker}' has no analysis_date configured."
        )

    if not provider_symbol:
        raise HTTPException(
            status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol resolved."
        )

    hist_lookup = fetch_hist_fn or provider.fetch_historical_quote_and_date
    res = hist_lookup(provider_symbol, parsed_target_date, 10)
    if not res:
        raise HTTPException(
            status_code=404,
            detail=f"No market quote found on Yahoo Finance for {provider_symbol} on or near {parsed_target_date}.",
        )

    price, actual_dt = res
    store.save_analysis_price(target_id, Decimal(str(price)), actual_dt)
    invalidate_positions_cache(user_id)
    return {
        "status": "ok",
        "ticker": inst_ticker,
        "analysis_date": actual_dt.isoformat(),
        "analysis_reference_price": price,
    }


def fetch_ytd_price(
    ticker: str,
    target_year: Optional[int],
    user_id: uuid.UUID,
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    fetch_soy_fn: Optional[Callable[[str, Optional[int]], Optional[tuple[float, date]]]] = None,
) -> dict:
    """Resolve and persist an instrument's start-of-year price using short DB sessions."""
    target = store.get_ytd_lookup_target(ticker)
    if not target:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    target_id, inst_ticker, inst_soy_date, provider_symbol = target
    year = target_year or (inst_soy_date.year if inst_soy_date else date.today().year)
    if not provider_symbol:
        raise HTTPException(
            status_code=400, detail=f"Instrument '{ticker}' has no provider_symbol resolved."
        )

    soy_lookup = fetch_soy_fn or provider.fetch_start_of_year_quote
    res = soy_lookup(provider_symbol, year)
    if not res:
        raise HTTPException(
            status_code=404,
            detail=f"No start-of-year quote found on Yahoo Finance for {provider_symbol} in year {year}.",
        )

    price, actual_dt = res
    store.save_ytd_price(target_id, Decimal(str(price)), actual_dt)
    invalidate_positions_cache(user_id)
    return {
        "status": "ok",
        "ticker": inst_ticker,
        "start_of_year_date": actual_dt.isoformat(),
        "start_of_year_price": price,
    }


def resolve_candidates_parallel(
    candidates: list[tuple[Any, Callable[[], Optional[tuple[float, date]]]]],
) -> tuple[list[tuple[Any, float, date]], int]:
    """Execute Yahoo historical lookups concurrently outside DB sessions."""
    if not candidates:
        return [], 0

    def _run_one(item):
        key, fn = item
        try:
            res = fn()
            if res:
                return key, res[0], res[1]
        except Exception as e:
            logger.debug("Error resolving historical price: %s", e)
        return key, None, None

    resolved: list[tuple[Any, float, date]] = []
    failed = 0
    max_workers = min(8, len(candidates))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for key, price_val, dt_val in pool.map(_run_one, candidates):
            if price_val is not None and dt_val is not None:
                resolved.append((key, price_val, dt_val))
            else:
                failed += 1
    return resolved, failed


def resolve_missing_analysis_prices(
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    user_id: Optional[uuid.UUID] = None,
    fetch_hist_fn: Optional[Callable[[str, date, int], Optional[tuple[float, date]]]] = None,
) -> dict:
    """Batch-resolve missing analysis reference prices across active instruments."""
    total, raw_candidates, missing_sym_failed = store.list_missing_analysis_candidates()
    hist_lookup = fetch_hist_fn or provider.fetch_historical_quote_and_date
    candidates = [
        (row_id, lambda s=prov_sym, d=an_dt: hist_lookup(s, d, 10))
        for row_id, prov_sym, an_dt in raw_candidates
    ]
    resolved, fetch_failed = resolve_candidates_parallel(candidates)
    if resolved:
        store.save_missing_analysis_prices(
            [(row_id, Decimal(str(price_val)), dt_val) for row_id, price_val, dt_val in resolved]
        )
    invalidate_positions_cache(user_id)
    return {
        "status": "ok",
        "updated": len(resolved),
        "failed": fetch_failed + missing_sym_failed,
        "skipped": total - len(candidates) - missing_sym_failed,
        "total": total,
    }


def resolve_missing_ytd_prices(
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    user_id: Optional[uuid.UUID] = None,
    fetch_soy_fn: Optional[Callable[[str, Optional[int]], Optional[tuple[float, date]]]] = None,
) -> dict:
    """Batch-resolve missing start-of-year prices across active instruments."""
    current_year = date.today().year
    total, raw_candidates, missing_sym_failed = store.list_missing_ytd_candidates()
    soy_lookup = fetch_soy_fn or provider.fetch_start_of_year_quote
    candidates = [
        (row_id, lambda s=prov_sym, y=current_year: soy_lookup(s, y))
        for row_id, prov_sym in raw_candidates
    ]
    resolved, fetch_failed = resolve_candidates_parallel(candidates)
    if resolved:
        store.save_missing_ytd_prices(
            [(row_id, Decimal(str(price_val)), dt_val) for row_id, price_val, dt_val in resolved]
        )
    invalidate_positions_cache(user_id)
    return {
        "status": "ok",
        "updated": len(resolved),
        "failed": fetch_failed + missing_sym_failed,
        "skipped": total - len(candidates) - missing_sym_failed,
        "total": total,
    }
