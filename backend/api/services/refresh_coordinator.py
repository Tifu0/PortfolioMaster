"""Coordinator for batch and single-instrument market data refresh."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Dict, Optional

from fastapi import HTTPException

from portfoliomaster.core.config import get_batch_size
from portfoliomaster.core.models import Quote
from portfoliomaster.core.parsing import safe_float
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.providers.yahoo_adapter import YahooAdapter
from portfoliomaster.refresh.batch_runner import BatchRunner

from ..common import is_production
from .cache import invalidate_positions_cache
from .instrument_service import (
    resolve_missing_analysis_prices,
    resolve_missing_ytd_prices,
)
from .refresh_sse import (
    broadcast_refresh_event,
    get_refresh_state_snapshot,
    mark_refresh_error,
    mark_refresh_finished,
    mark_refresh_started,
    set_refresh_plan,
    update_state_on_batch,
    update_state_on_completion,
)

logger = logging.getLogger(__name__)

STALE_THRESHOLD_SECONDS = int(os.environ.get("REFRESH_COOLDOWN_SECONDS", "120"))
STALE_THRESHOLD_SINGLE_SECONDS = int(os.environ.get("REFRESH_SINGLE_COOLDOWN_SECONDS", "30"))

_refresh_lock = threading.Lock()
_user_refresh_locks: Dict[uuid.UUID, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def get_user_refresh_lock(
    user_id: Optional[uuid.UUID], *, multi_tenant: Optional[bool] = None
) -> threading.Lock:
    """Return a per-tenant mutual-exclusion lock in multi-tenant mode, or global lock."""
    use_per_user = (user_id is not None) if multi_tenant is None else (multi_tenant and user_id is not None)
    if not use_per_user or user_id is None:
        return _refresh_lock
    with _user_locks_guard:
        lock = _user_refresh_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_refresh_locks[user_id] = lock
        return lock


def is_user_refreshing(user_id: uuid.UUID, multi_tenant: bool) -> bool:
    """Return whether a refresh lock is currently held for the tenant (or globally in SQLite)."""
    if multi_tenant:
        return get_user_refresh_lock(user_id, multi_tenant=True).locked()
    return bool(get_refresh_state_snapshot().get("is_refreshing"))


def _emit_event(
    payload: dict,
    *,
    user_id: Optional[uuid.UUID],
    on_batch_progress: Optional[Callable[[dict], None]],
    broadcast_fn: Callable[..., None],
) -> None:
    broadcast_fn(payload, target_user_id=user_id)
    if on_batch_progress:
        try:
            on_batch_progress(payload)
        except Exception as ex:
            logger.debug("Error in on_batch_progress: %s", ex)


def execute_refresh_all(
    store: PortfolioStore,
    provider: YahooAdapter,
    *,
    on_batch_progress: Optional[Callable[[dict], None]] = None,
    force: bool = False,
    user_id: Optional[uuid.UUID] = None,
    stale_threshold_seconds: int = STALE_THRESHOLD_SECONDS,
    broadcast_fn: Callable[..., None] = broadcast_refresh_event,
    resolve_analysis_fn: Optional[Callable[..., dict]] = None,
    resolve_ytd_fn: Optional[Callable[..., dict]] = None,
) -> dict:
    """Execute 3-phase batch quote refresh (short DB prep -> Yahoo chunks -> short DB persist)."""
    multi_tenant = not store.supports_sqlite_file_backups
    lock = get_user_refresh_lock(user_id, multi_tenant=multi_tenant)
    if not lock.acquire(blocking=False):
        return {"status": "in_progress", "detail": "Refresh is already in progress."}

    mark_refresh_started()
    run_id = None

    try:
        now_utc = datetime.now(timezone.utc)
        prep = store.check_and_prepare_batch_refresh(
            now_utc=now_utc,
            force=force,
            stale_seconds=stale_threshold_seconds,
        )
        state = prep["state"]

        if state == "in_progress":
            return {"status": "in_progress", "detail": prep.get("detail", "Refresh is already in progress.")}

        if state == "empty":
            result = {"status": "ok", "updated": 0, "failed": 0, "total": 0, "refreshed_count": 0}
            update_state_on_completion(result, 0)
            if store.supports_sqlite_file_backups:
                _emit_event(
                    {"type": "start", "total_symbols": 0, "total_batches": 0, "batch_size": get_batch_size()},
                    user_id=user_id,
                    on_batch_progress=on_batch_progress,
                    broadcast_fn=broadcast_fn,
                )
            _emit_event(
                {
                    "type": "complete",
                    "status": "ok",
                    "updated": 0,
                    "failed": 0,
                    "total": 0,
                    "refreshed_count": 0,
                    "analysis_prices_updated": 0,
                    "ytd_prices_updated": 0,
                },
                user_id=user_id,
                on_batch_progress=on_batch_progress,
                broadcast_fn=broadcast_fn,
            )
            return result

        if state == "fresh":
            total_symbols = prep.get("total_symbols", 0)
            logger.info(
                "[Refresh] All %d symbols are fresh (within %ds cooldown). Skipping Yahoo calls.",
                total_symbols,
                stale_threshold_seconds,
            )
            result = {
                "status": "fresh",
                "message": "Precios actualizados recientemente",
                "refreshed_count": 0,
                "total_symbols": total_symbols,
                "updated": 0,
                "failed": 0,
                "total": total_symbols,
            }
            if prep.get("detail") is not None:
                result["detail"] = prep["detail"]
            update_state_on_completion(result, total_symbols)
            _emit_event(
                {
                    "type": "complete",
                    "status": "fresh",
                    "message": "Precios actualizados recientemente",
                    "refreshed_count": 0,
                    "total_symbols": total_symbols,
                    "updated": 0,
                    "failed": 0,
                    "total": total_symbols,
                },
                user_id=user_id,
                on_batch_progress=on_batch_progress,
                broadcast_fn=broadcast_fn,
            )
            return result

        # state == "ready"
        run_id = prep.get("run_id")
        stale_symbols = prep["stale_symbols"]
        total_symbols = prep["total_symbols"]
        symbol_counts = prep.get("symbol_counts", {})
        symbol_currencies = prep.get("symbol_currencies", {})
        existing_quote_symbols = prep.get("existing_quote_symbols", set())
        instrument_map = prep.get("instrument_map", {})

        batch_size = get_batch_size()
        stale_count = len(stale_symbols)
        total_batches = (stale_count + batch_size - 1) // batch_size if stale_count > 0 else 0
        set_refresh_plan(stale_count, total_batches)

        _emit_event(
            {
                "type": "start",
                "total_symbols": stale_count,
                "total_batches": total_batches,
                "batch_size": batch_size,
            },
            user_id=user_id,
            on_batch_progress=on_batch_progress,
            broadcast_fn=broadcast_fn,
        )

        updated = 0
        failed = 0
        processed_count = 0

        def on_batch(batch_idx: int, total_b: int, chunk_quotes: Dict[str, Quote]):
            nonlocal updated, failed, processed_count
            prev_updated = updated
            prev_failed = failed

            processed_count, updated, failed, batch_updated = store.persist_refresh_batch(
                run_id=run_id,
                chunk_quotes=chunk_quotes,
                symbol_counts=symbol_counts,
                symbol_currencies=symbol_currencies,
                existing_quote_symbols=existing_quote_symbols,
                instrument_map=instrument_map,
                processed_count=processed_count,
                updated=updated,
                failed=failed,
            )
            batch_failed = failed - prev_failed
            batch_updated = max(batch_updated, updated - prev_updated)

            invalidate_positions_cache()
            processed_snap = update_state_on_batch(batch_idx, total_b, processed_count, stale_count)

            quotes_delta_payload = {}
            for sym, quote in chunk_quotes.items():
                if quote.is_valid():
                    quotes_delta_payload[sym] = {
                        "price": safe_float(quote.price),
                        "previous_close": safe_float(quote.previous_close),
                        "status": quote.status.name if hasattr(quote.status, "name") else str(quote.status),
                        "quote_timestamp": quote.quote_timestamp.isoformat() if quote.quote_timestamp else None,
                    }

            _emit_event(
                {
                    "type": "batch",
                    "batch_index": batch_idx,
                    "total_batches": total_b,
                    "processed_symbols": processed_snap,
                    "total_symbols": stale_count,
                    "updated": updated,
                    "failed": failed,
                    "batch_updated": batch_updated,
                    "batch_failed": batch_failed,
                    "quotes": quotes_delta_payload,
                },
                user_id=user_id,
                on_batch_progress=on_batch_progress,
                broadcast_fn=broadcast_fn,
            )

        runner = BatchRunner(provider=provider, batch_size=batch_size)
        runner.run(stale_symbols, on_batch_complete=on_batch)

        result: dict = {
            "status": "ok",
            "updated": updated,
            "failed": failed,
            "total": total_symbols,
            "refreshed_count": updated,
            "stale_count": stale_count,
        }

        if not multi_tenant or user_id is not None:
            try:
                if resolve_analysis_fn is not None:
                    analysis_res = resolve_analysis_fn(user_id=user_id)
                else:
                    analysis_res = resolve_missing_analysis_prices(store, provider, user_id=user_id)
                if analysis_res.get("updated", 0) > 0:
                    result["analysis_prices_updated"] = analysis_res["updated"]
            except Exception as e:
                logger.warning("Could not auto-resolve missing analysis prices: %s", e)

            try:
                if resolve_ytd_fn is not None:
                    ytd_res = resolve_ytd_fn(user_id=user_id)
                else:
                    ytd_res = resolve_missing_ytd_prices(store, provider, user_id=user_id)
                if ytd_res.get("updated", 0) > 0:
                    result["ytd_prices_updated"] = ytd_res["updated"]
            except Exception as e:
                logger.warning("Could not auto-resolve missing YTD prices: %s", e)

        if run_id:
            try:
                store.complete_refresh_run(
                    run_id=run_id,
                    status="COMPLETED",
                    diagnostic_summary=f"Processed {processed_count} symbols: {updated} updated, {failed} failed.",
                )
            except Exception as ex:
                logger.debug("Could not mark RefreshRun completed: %s", ex)

        update_state_on_completion(result, total_symbols)
        invalidate_positions_cache()

        _emit_event(
            {
                "type": "complete",
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "total": total_symbols,
                "refreshed_count": updated,
                "analysis_prices_updated": result.get("analysis_prices_updated", 0),
                "ytd_prices_updated": result.get("ytd_prices_updated", 0),
            },
            user_id=user_id,
            on_batch_progress=on_batch_progress,
            broadcast_fn=broadcast_fn,
        )
        return result

    except Exception as e:
        logger.error("Exception in refresh_all: %s", e)
        if run_id:
            try:
                store.complete_refresh_run(
                    run_id=run_id,
                    status="FAILED",
                    error_message=str(e)[:500],
                )
            except Exception:
                pass

        public_err = "Refresh failed due to an internal error." if is_production() else str(e)
        mark_refresh_error(f"error: {public_err}")
        _emit_event(
            {
                "type": "error",
                "detail": "Refresh failed due to an internal error." if is_production() else "Refresh failed.",
            },
            user_id=user_id,
            on_batch_progress=on_batch_progress,
            broadcast_fn=broadcast_fn,
        )
        return {"status": "error", "detail": public_err}

    finally:
        mark_refresh_finished()
        lock.release()


def trigger_refresh(
    *,
    force: bool,
    background: bool,
    user_id: uuid.UUID,
    store: PortfolioStore,
    provider: YahooAdapter,
    execute_fn: Optional[Callable[..., dict]] = None,
) -> dict:
    """Coordinate manual POST /api/refresh execution synchronously or on a daemon thread."""
    multi_tenant = not store.supports_sqlite_file_backups
    lock = get_user_refresh_lock(user_id, multi_tenant=multi_tenant)
    if lock.locked():
        return {"status": "in_progress", "detail": "Refresh is already in progress."}

    if multi_tenant:
        try:
            active_run = store.get_active_refresh_run()
            if active_run is not None:
                # Re-verify user scope via lightweight check_and_prepare? Wait: preserve exact semantics:
                # get_active_refresh_run checks global RUNNING; check tenant-specific only if needed
                from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository
                from portfoliomaster.db import session as db_session

                with db_session.session_scope() as session:
                    if RefreshRunRepository(session).is_running(scope="USER", user_id=user_id):
                        return {"status": "in_progress", "detail": "Refresh is already in progress for this user."}
        except Exception as ex:
            logger.debug("Database refresh run check skipped: %s", ex)

    runner_fn = execute_fn or (lambda **kw: execute_refresh_all(store, provider, **kw))
    if background:
        t = threading.Thread(
            target=runner_fn,
            kwargs={"force": force, "user_id": user_id},
            daemon=True,
        )
        t.start()
        return {"status": "triggered"}

    return runner_fn(force=force, user_id=user_id)


def refresh_single_instrument(
    ticker: str,
    *,
    force: bool,
    user_id: uuid.UUID,
    store: PortfolioStore,
    provider: YahooAdapter,
    single_cooldown_seconds: int = STALE_THRESHOLD_SINGLE_SECONDS,
    hist_scalar_fn: Optional[Callable[[str, date], Optional[float]]] = None,
    soy_fn: Optional[Callable[[str, Optional[int]], Optional[tuple[float, date]]]] = None,
) -> dict:
    """Refresh quote and missing reference prices for a single instrument with cooldown."""
    now_utc = datetime.now(timezone.utc)
    target = store.get_single_refresh_target(
        ticker=ticker,
        now_utc=now_utc,
        force=force,
        single_cooldown_seconds=single_cooldown_seconds,
    )
    if not target:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    if target.get("fresh_payload") is not None:
        return target["fresh_payload"]

    symbol = target["symbol"]
    quotes = provider.fetch([symbol])
    if symbol not in quotes:
        raise HTTPException(status_code=502, detail=f"No response from Yahoo for '{symbol}'")

    fetched_quote = quotes[symbol]
    resolved_analysis_price: Optional[Decimal] = None
    if target.get("analysis_date") and not target.get("analysis_reference_price"):
        try:
            hist_lookup = hist_scalar_fn or provider.fetch_historical_quote_for_date
            hist_p = hist_lookup(symbol, target["analysis_date"])
            if hist_p is not None:
                resolved_analysis_price = Decimal(str(hist_p))
        except Exception as e:
            logger.debug("Error auto-resolving analysis price for %s: %s", ticker, e)

    resolved_soy_price: Optional[Decimal] = None
    resolved_soy_date: Optional[date] = None
    if not target.get("start_of_year_price"):
        try:
            current_year = date.today().year
            soy_lookup = soy_fn or provider.fetch_start_of_year_quote
            res_ytd = soy_lookup(symbol, current_year)
            if res_ytd:
                p_val, actual_dt = res_ytd
                resolved_soy_price = Decimal(str(p_val))
                resolved_soy_date = actual_dt
        except Exception as e:
            logger.debug("Error auto-resolving YTD price for %s: %s", ticker, e)

    result = store.save_single_refresh_result(
        target=target,
        fetched_quote=fetched_quote,
        resolved_analysis_price=resolved_analysis_price,
        resolved_soy_price=resolved_soy_price,
        resolved_soy_date=resolved_soy_date,
    )
    invalidate_positions_cache(user_id if store.supports_sqlite_file_backups else None)
    return result
