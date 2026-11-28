"""Batch refresh and live SSE streaming router for watchlistTracker (WT)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Dict, List, Optional, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from portfoliomaster.core.config import get_batch_size, get_yahoo_suffix
from portfoliomaster.core.models import Quote
from portfoliomaster.db.repository import (
    get_all_instruments,
    get_instrument_by_ticker,
    get_quote_by_instrument_id,
    update_instrument_by_id,
    upsert_instrument,
    upsert_quote,
)
from portfoliomaster.ingest.normalizer import normalize
from portfoliomaster.providers.yahoo_adapter import YahooAdapter
from portfoliomaster.refresh.batch_runner import BatchRunner
from .instruments import (
    _fetch_historical_quote_and_date,
    _fetch_start_of_year_quote,
    _resolve_missing_analysis_prices_sync,
    _resolve_missing_ytd_prices_sync,
)
from .positions import invalidate_positions_cache
from ..common import (
    _quote_to_dict,
    _to_float,
    get_current_user_id,
    is_multi_tenant_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["refresh"])

# Configurable cooldown thresholds (seconds)
STALE_THRESHOLD_SECONDS = int(os.environ.get("REFRESH_COOLDOWN_SECONDS", "120"))
STALE_THRESHOLD_SINGLE_SECONDS = int(os.environ.get("REFRESH_SINGLE_COOLDOWN_SECONDS", "30"))


class RefreshStateDict(TypedDict, total=False):
    is_refreshing: bool
    last_refresh_at: Optional[str]
    last_refresh_result: Optional[dict[str, object] | str]
    last_refresh_time: Optional[str]
    last_refresh_status: Optional[str]
    total_batches: int
    current_batch: int
    total_symbols: int
    processed_symbols: int
    refresh_counter: int


# Shared refresh state and subscriber queues
_state: RefreshStateDict = {
    "is_refreshing": False,
    "last_refresh_at": None,
    "last_refresh_result": None,
    "last_refresh_time": None,
    "last_refresh_status": None,
    "total_batches": 0,
    "current_batch": 0,
    "total_symbols": 0,
    "processed_symbols": 0,
    "refresh_counter": 0,
}
_state_lock = threading.Lock()
_refresh_lock = threading.Lock()
_user_refresh_locks: Dict[uuid.UUID, threading.Lock] = {}
_user_locks_guard = threading.Lock()


@dataclass(eq=False)
class _SSESubscriber:
    """Tenant-scoped non-blocking SSE subscriber backed by bounded asyncio.Queue."""

    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    user_id: uuid.UUID
    allowed_symbols: Optional[frozenset[str]] = field(default=None)


_sse_subscribers: set[_SSESubscriber] = set()
_sse_lock = threading.Lock()


def _get_user_refresh_lock(user_id: Optional[uuid.UUID]) -> threading.Lock:
    """Return a per-tenant mutual-exclusion lock in multi-tenant mode, or global lock."""
    if user_id is None or not is_multi_tenant_db():
        return _refresh_lock
    with _user_locks_guard:
        lock = _user_refresh_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _user_refresh_locks[user_id] = lock
        return lock


def get_refresh_state_snapshot() -> RefreshStateDict:
    """Return a thread-safe shallow copy of the refresh state dictionary."""
    with _state_lock:
        return dict(_state)


def _get_active_sse_subscribers_count() -> int:
    """Return the number of connected SSE subscriber queues."""
    with _sse_lock:
        return len(_sse_subscribers)


def _enqueue_nonblocking(q: asyncio.Queue, item: dict) -> None:
    """Enqueue an SSE payload without blocking; drop oldest item if QueueFull."""
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            pass


def _filter_payload_for_subscriber(
    payload: dict,
    sub: _SSESubscriber,
    target_user_id: Optional[uuid.UUID],
) -> Optional[dict]:
    """Filter SSE events strictly by tenant and allowed symbols."""
    if target_user_id is not None:
        if sub.user_id != target_user_id:
            return None
        return payload

    if sub.allowed_symbols is not None and isinstance(payload.get("quotes"), dict):
        filtered_quotes = {
            sym: qdata
            for sym, qdata in payload["quotes"].items()
            if sym in sub.allowed_symbols
        }
        return {**payload, "quotes": filtered_quotes}

    return payload


def _broadcast_refresh_event(
    payload: dict,
    target_user_id: Optional[uuid.UUID] = None,
) -> None:
    """Thread-safe event broadcast to matching tenant SSE clients via asyncio.Queue."""
    if payload.get("type") == "complete":
        with _state_lock:
            payload = {
                **payload,
                "last_refresh_at": _state["last_refresh_at"],
                "refresh_counter": _state["refresh_counter"],
            }
    with _sse_lock:
        subscribers = list(_sse_subscribers)
    for sub in subscribers:
        filtered = _filter_payload_for_subscriber(payload, sub, target_user_id)
        if filtered is None:
            continue
        try:
            if not sub.loop.is_closed():
                sub.loop.call_soon_threadsafe(_enqueue_nonblocking, sub.queue, filtered)
        except RuntimeError:
            pass


def _update_state_on_completion(result: dict, total_symbols: int) -> None:
    """Helper to update internal _state dictionary consistently."""
    now_iso = datetime.now(timezone.utc).isoformat()
    status = result.get("status", "ok")
    updated = result.get("updated", 0)
    with _state_lock:
        _state["last_refresh_at"] = now_iso
        _state["last_refresh_time"] = now_iso
        _state["last_refresh_result"] = result
        if status == "fresh":
            _state["last_refresh_status"] = "fresh (al día)"
        else:
            _state["last_refresh_status"] = f"ok ({updated}/{total_symbols} updated)"
        _state["refresh_counter"] = _state.get("refresh_counter", 0) + 1


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


def _get_historical_quote_for_date(provider_symbol: str, target_date: date) -> Optional[float]:
    import sys
    main_mod = sys.modules.get("backend.api.main")
    if main_mod and hasattr(main_mod, "_fetch_historical_quote_for_date"):
        fn = getattr(main_mod, "_fetch_historical_quote_for_date")
        return fn(provider_symbol, target_date)
    res = _fetch_historical_quote_and_date(provider_symbol, target_date, window_days=10)
    return res[0] if res else None


def _get_start_of_year_quote(provider_symbol: str, year: Optional[int] = None) -> Optional[tuple[float, date]]:
    import sys
    main_mod = sys.modules.get("backend.api.main")
    if main_mod and hasattr(main_mod, "_fetch_start_of_year_quote"):
        fn = getattr(main_mod, "_fetch_start_of_year_quote")
        return fn(provider_symbol, year)
    return _fetch_start_of_year_quote(provider_symbol, year)


def _execute_refresh_all(
    on_batch_progress: Optional[Callable[[dict], None]] = None,
    force: bool = False,
    user_id: Optional[uuid.UUID] = None,
) -> dict:
    """Core batch refresh engine with per-tenant isolation, cooldown, and symbol deduplication."""
    lock = _get_user_refresh_lock(user_id)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        return {"status": "in_progress", "detail": "Refresh is already in progress."}

    with _state_lock:
        _state["is_refreshing"] = True
        _state["current_batch"] = 0
        _state["processed_symbols"] = 0

    try:
        now_utc = datetime.now(timezone.utc)

        if is_multi_tenant_db():
            import portfoliomaster.db.session as db_session
            from portfoliomaster.db.schema import UserInstrument, MarketQuote, RefreshRun
            from portfoliomaster.db.multi_tenant_repository import (
                GlobalMarketQuotesRepository,
                RefreshRunRepository,
                clear_quote_delta_cache,
                filter_unchanged_quotes,
            )
            from sqlalchemy import select

            run_id = None
            symbol_counts: Dict[str, int] = {}
            symbol_currencies: Dict[str, str] = {}
            stale_symbols: List[str] = []
            existing_quote_symbols: set[str] = set()
            total_symbols = 0

            # Phase 1: Short DB read + per-tenant cooldown + RefreshRun initialization (exit before Yahoo I/O)
            with db_session.session_scope() as session:
                run_repo = RefreshRunRepository(session)
                cutoff = now_utc - timedelta(minutes=10)
                try:
                    stale_runs = session.scalars(
                        select(RefreshRun).where(
                            RefreshRun.status == "RUNNING",
                            RefreshRun.started_at < cutoff,
                        )
                    ).all()
                    for sr in stale_runs:
                        sr.status = "TIMEOUT"
                        sr.diagnostic_summary = "Timed out after 10 minutes without completion."
                    if stale_runs:
                        session.flush()
                except Exception as ex:
                    logger.debug("Stale run check skipped: %s", ex)

                if user_id is not None:
                    can_rf, cooldown_msg = run_repo.can_user_refresh(
                        user_id, cooldown_seconds=STALE_THRESHOLD_SECONDS
                    )
                    if not can_rf:
                        if cooldown_msg and "already have a refresh in progress" in cooldown_msg:
                            return {"status": "in_progress", "detail": cooldown_msg}
                        if not force:
                            result = {
                                "status": "fresh",
                                "message": "Precios actualizados recientemente",
                                "detail": cooldown_msg,
                                "refreshed_count": 0,
                                "total_symbols": 0,
                                "updated": 0,
                                "failed": 0,
                                "total": 0,
                            }
                            _update_state_on_completion(result, 0)
                            complete_payload = {
                                "type": "complete",
                                "status": "fresh",
                                "message": "Precios actualizados recientemente",
                                "refreshed_count": 0,
                                "total_symbols": 0,
                                "updated": 0,
                                "failed": 0,
                                "total": 0,
                            }
                            _broadcast_refresh_event(complete_payload, target_user_id=user_id)
                            if on_batch_progress:
                                try:
                                    on_batch_progress(complete_payload)
                                except Exception:
                                    pass
                            return result
                elif run_repo.is_running(scope="GLOBAL"):
                    logger.info("[Refresh] Another refresh run is currently active in the database. Skipping duplicate execution.")
                    return {"status": "in_progress", "detail": "Refresh is already in progress across instances."}

                stmt = select(
                    UserInstrument.provider_symbol,
                    UserInstrument.user_ticker,
                    UserInstrument.currency,
                ).where(UserInstrument.active.is_(True))
                if user_id is not None:
                    stmt = stmt.where(UserInstrument.user_id == user_id)

                rows = session.execute(stmt).all()
                total_inst = len(rows)
                if total_inst == 0:
                    result = {
                        "status": "ok",
                        "updated": 0,
                        "failed": 0,
                        "total": 0,
                        "refreshed_count": 0,
                    }
                    _update_state_on_completion(result, 0)
                    complete_payload = {
                        "type": "complete",
                        "status": "ok",
                        "updated": 0,
                        "failed": 0,
                        "total": 0,
                        "refreshed_count": 0,
                    }
                    _broadcast_refresh_event(complete_payload, target_user_id=user_id)
                    if on_batch_progress:
                        try:
                            on_batch_progress(complete_payload)
                        except Exception:
                            pass
                    return result

                for prov_sym, usr_ticker, curr in rows:
                    sym = (prov_sym or usr_ticker or "").strip().upper()
                    if sym:
                        symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
                        if curr and sym not in symbol_currencies:
                            symbol_currencies[sym] = curr

                unique_symbols = list(symbol_counts.keys())
                total_symbols = len(unique_symbols)

                if force:
                    clear_quote_delta_cache(symbols=unique_symbols)

                quotes_stmt = select(MarketQuote.provider_symbol, MarketQuote.last_attempt_at).where(
                    MarketQuote.provider_symbol.in_(unique_symbols)
                )
                existing_attempts = {sym: last_at for sym, last_at in session.execute(quotes_stmt).all()}
                existing_quote_symbols = set(existing_attempts.keys())

                for sym in unique_symbols:
                    if force:
                        stale_symbols.append(sym)
                        continue
                    last_attempt = existing_attempts.get(sym)
                    if last_attempt is None:
                        stale_symbols.append(sym)
                    else:
                        last_ts = last_attempt if last_attempt.tzinfo else last_attempt.replace(tzinfo=timezone.utc)
                        elapsed = (now_utc - last_ts).total_seconds()
                        if elapsed >= STALE_THRESHOLD_SECONDS:
                            stale_symbols.append(sym)

                if not stale_symbols:
                    logger.info(
                        "[Refresh] All %d symbols are fresh (within %ds cooldown). Skipping Yahoo calls.",
                        total_symbols,
                        STALE_THRESHOLD_SECONDS,
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
                    _update_state_on_completion(result, total_symbols)
                    complete_payload = {
                        "type": "complete",
                        "status": "fresh",
                        "message": "Precios actualizados recientemente",
                        "refreshed_count": 0,
                        "total_symbols": total_symbols,
                        "updated": 0,
                        "failed": 0,
                        "total": total_symbols,
                    }
                    _broadcast_refresh_event(complete_payload, target_user_id=user_id)
                    if on_batch_progress:
                        try:
                            on_batch_progress(complete_payload)
                        except Exception:
                            pass
                    return result

                stale_count = len(stale_symbols)
                try:
                    run = run_repo.start_run(
                        total_symbols=stale_count,
                        trigger_type="manual" if user_id is not None else "batch_worker",
                        user_id=user_id,
                    )
                    run_id = run.id
                except Exception as ex:
                    logger.debug("Optional refresh_run record skipped: %s", ex)

            # Phase 2: Network I/O outside any DB session; brief session per batch persistence
            provider = _get_yahoo_adapter()
            batch_size = get_batch_size()
            stale_count = len(stale_symbols)
            total_batches = (stale_count + batch_size - 1) // batch_size if stale_count > 0 else 0

            with _state_lock:
                _state["current_batch"] = 0
                _state["total_batches"] = total_batches
                _state["processed_symbols"] = 0
                _state["total_symbols"] = stale_count

            start_payload = {
                "type": "start",
                "total_symbols": stale_count,
                "total_batches": total_batches,
                "batch_size": batch_size,
            }
            _broadcast_refresh_event(start_payload, target_user_id=user_id)
            if on_batch_progress:
                try:
                    on_batch_progress(start_payload)
                except Exception as ex:
                    logger.debug("Error in on_batch_progress (start): %s", ex)

            updated = 0
            failed = 0
            processed_count = 0

            def on_batch_pg(batch_idx: int, total_b: int, chunk_quotes: Dict[str, Quote]):
                nonlocal updated, failed, processed_count
                batch_updated = 0
                batch_failed = 0

                batch_quotes_payload = []
                for sym, quote in chunk_quotes.items():
                    status_str = quote.status.name if hasattr(quote.status, "name") else str(quote.status)
                    batch_quotes_payload.append({
                        "provider_symbol": sym,
                        "price": quote.price,
                        "previous_close": quote.previous_close,
                        "quote_timestamp": quote.quote_timestamp,
                        "status": status_str,
                        "error_message": quote.error_message,
                        "provider": quote.provider or "yahoo",
                        "currency": symbol_currencies.get(sym, "EUR"),
                    })
                    cnt = symbol_counts.get(sym, 1)
                    if quote.is_valid():
                        updated += cnt
                        batch_updated += cnt
                    else:
                        failed += cnt
                        batch_failed += cnt
                    processed_count += 1

                deltas_to_write = filter_unchanged_quotes(batch_quotes_payload)
                delta_syms = {d["provider_symbol"] for d in deltas_to_write}
                unchanged_existing_syms: list[str] = []
                for item in batch_quotes_payload:
                    psym = item["provider_symbol"]
                    if psym not in delta_syms:
                        if psym in existing_quote_symbols:
                            unchanged_existing_syms.append(psym)
                        else:
                            deltas_to_write.append(item)
                            existing_quote_symbols.add(psym)

                with db_session.session_scope() as batch_session:
                    quotes_repo = GlobalMarketQuotesRepository(batch_session)
                    if deltas_to_write:
                        quotes_repo.upsert_market_quotes_batch(deltas_to_write)
                        existing_quote_symbols.update(d["provider_symbol"] for d in deltas_to_write)
                    if unchanged_existing_syms:
                        quotes_repo.touch_last_attempt_at(unchanged_existing_syms, datetime.now(timezone.utc))
                    if run_id:
                        try:
                            RefreshRunRepository(batch_session).update_progress(
                                run_id=run_id,
                                processed=processed_count,
                                successful=updated,
                                failed=failed,
                            )
                        except Exception as ex:
                            logger.debug("Could not update run progress: %s", ex)

                invalidate_positions_cache()

                with _state_lock:
                    _state["current_batch"] = batch_idx
                    _state["total_batches"] = total_b
                    _state["processed_symbols"] = min(processed_count, stale_count)
                    _state["total_symbols"] = stale_count
                    _state["refresh_counter"] = _state.get("refresh_counter", 0) + 1
                    processed_snap = _state["processed_symbols"]

                quotes_delta_payload = {}
                for sym, quote in chunk_quotes.items():
                    if quote.is_valid():
                        quotes_delta_payload[sym] = {
                            "price": _to_float(quote.price),
                            "previous_close": _to_float(quote.previous_close),
                            "status": quote.status.name if hasattr(quote.status, "name") else str(quote.status),
                            "quote_timestamp": quote.quote_timestamp.isoformat() if quote.quote_timestamp else None,
                        }

                batch_payload = {
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
                }
                _broadcast_refresh_event(batch_payload, target_user_id=user_id)
                if on_batch_progress:
                    try:
                        on_batch_progress(batch_payload)
                    except Exception as ex:
                        logger.debug("Error in on_batch_progress (batch): %s", ex)

            runner = BatchRunner(provider=provider, batch_size=batch_size)
            runner.run(stale_symbols, on_batch_complete=on_batch_pg)

            result = {
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "total": total_symbols,
                "refreshed_count": updated,
                "stale_count": stale_count,
            }

            if user_id is not None:
                try:
                    analysis_res = _resolve_missing_analysis_prices_sync(user_id=user_id)
                    if analysis_res.get("updated", 0) > 0:
                        result["analysis_prices_updated"] = analysis_res["updated"]
                except Exception as e:
                    logger.warning("Could not auto-resolve missing analysis prices: %s", e)

                try:
                    ytd_res = _resolve_missing_ytd_prices_sync(user_id=user_id)
                    if ytd_res.get("updated", 0) > 0:
                        result["ytd_prices_updated"] = ytd_res["updated"]
                except Exception as e:
                    logger.warning("Could not auto-resolve missing YTD prices: %s", e)

            # Phase 3: Mark RefreshRun completed in brief session
            if run_id:
                try:
                    with db_session.session_scope() as done_session:
                        RefreshRunRepository(done_session).complete_run(
                            run_id=run_id,
                            status="COMPLETED",
                            diagnostic_summary=f"Processed {processed_count} symbols: {updated} updated, {failed} failed.",
                        )
                except Exception as ex:
                    logger.debug("Could not mark RefreshRun completed: %s", ex)

            _update_state_on_completion(result, total_symbols)
            invalidate_positions_cache()

            complete_payload = {
                "type": "complete",
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "total": total_symbols,
                "refreshed_count": updated,
                "analysis_prices_updated": result.get("analysis_prices_updated", 0),
                "ytd_prices_updated": result.get("ytd_prices_updated", 0),
            }
            _broadcast_refresh_event(complete_payload, target_user_id=user_id)
            if on_batch_progress:
                try:
                    on_batch_progress(complete_payload)
                except Exception as ex:
                    logger.debug("Error in on_batch_progress (complete): %s", ex)
            return result

        else:
            # SQLite mode
            instruments = get_all_instruments(include_inactive=False)
            total_inst = len(instruments)

            if total_inst == 0:
                result = {"status": "ok", "updated": 0, "failed": 0, "total": 0, "refreshed_count": 0}
                _update_state_on_completion(result, 0)
                start_payload = {
                    "type": "start",
                    "total_symbols": 0,
                    "total_batches": 0,
                    "batch_size": get_batch_size(),
                }
                complete_payload = {
                    "type": "complete",
                    "status": "ok",
                    "updated": 0,
                    "failed": 0,
                    "total": 0,
                    "refreshed_count": 0,
                    "analysis_prices_updated": 0,
                    "ytd_prices_updated": 0,
                }
                _broadcast_refresh_event(start_payload)
                _broadcast_refresh_event(complete_payload)
                if on_batch_progress:
                    try:
                        on_batch_progress(start_payload)
                        on_batch_progress(complete_payload)
                    except Exception:
                        pass
                return result

            # Re-normalise symbols before fetching
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

            # Map each provider_symbol to ALL matching instrument IDs
            instrument_map: Dict[str, List[int]] = {}
            for inst in instruments:
                if inst.provider_symbol and inst.id:
                    instrument_map.setdefault(inst.provider_symbol, []).append(inst.id)

            unique_symbols = list(instrument_map.keys())
            total_symbols = len(unique_symbols)

            # Evaluate staleness per unique symbol
            stale_symbols = []
            for sym, inst_ids in instrument_map.items():
                if force:
                    stale_symbols.append(sym)
                    continue
                needs_refresh = False
                for iid in inst_ids:
                    q = get_quote_by_instrument_id(iid)
                    if not q or q.fetched_at is None:
                        needs_refresh = True
                        break
                    last_ts = q.fetched_at if q.fetched_at.tzinfo else q.fetched_at.replace(tzinfo=timezone.utc)
                    if (now_utc - last_ts).total_seconds() >= STALE_THRESHOLD_SECONDS:
                        needs_refresh = True
                        break
                if needs_refresh:
                    stale_symbols.append(sym)

            if not stale_symbols:
                logger.info(
                    "[Refresh] All %d symbols are fresh (within %ds cooldown). Skipping Yahoo calls.",
                    total_symbols,
                    STALE_THRESHOLD_SECONDS,
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
                _update_state_on_completion(result, total_symbols)
                complete_payload = {
                    "type": "complete",
                    "status": "fresh",
                    "message": "Precios actualizados recientemente",
                    "refreshed_count": 0,
                    "total_symbols": total_symbols,
                    "updated": 0,
                    "failed": 0,
                    "total": total_symbols,
                }
                _broadcast_refresh_event(complete_payload)
                if on_batch_progress:
                    try:
                        on_batch_progress(complete_payload)
                    except Exception:
                        pass
                return result

            provider = _get_yahoo_adapter()
            batch_size = get_batch_size()
            stale_count = len(stale_symbols)
            total_batches = (stale_count + batch_size - 1) // batch_size if stale_count > 0 else 0

            _state["current_batch"] = 0
            _state["total_batches"] = total_batches
            _state["processed_symbols"] = 0
            _state["total_symbols"] = stale_count

            start_payload = {
                "type": "start",
                "total_symbols": stale_count,
                "total_batches": total_batches,
                "batch_size": batch_size,
            }
            _broadcast_refresh_event(start_payload)
            if on_batch_progress:
                try:
                    on_batch_progress(start_payload)
                except Exception as ex:
                    logger.debug("Error in on_batch_progress (start): %s", ex)

            updated = 0
            failed = 0
            processed_count = 0

            def on_batch_sqlite(batch_idx: int, total_b: int, chunk_quotes: Dict[str, Quote]):
                nonlocal updated, failed, processed_count
                batch_updated = 0
                batch_failed = 0

                for symbol, quote in chunk_quotes.items():
                    inst_ids = instrument_map.get(symbol, [])
                    for inst_id in inst_ids:
                        q_copy = Quote(
                            instrument_id=inst_id,
                            price=quote.price,
                            previous_close=quote.previous_close,
                            quote_timestamp=quote.quote_timestamp,
                            fetched_at=quote.fetched_at or datetime.now(timezone.utc),
                            provider=quote.provider,
                            status=quote.status,
                            error_message=quote.error_message,
                        )
                        upsert_quote(q_copy)

                    if inst_ids:
                        if quote.is_valid():
                            updated += len(inst_ids)
                            batch_updated += len(inst_ids)
                        else:
                            failed += len(inst_ids)
                            batch_failed += len(inst_ids)

                    processed_count += 1

                invalidate_positions_cache()
                _state["current_batch"] = batch_idx
                _state["total_batches"] = total_b
                _state["processed_symbols"] = min(processed_count, stale_count)
                _state["total_symbols"] = stale_count
                _state["refresh_counter"] = _state.get("refresh_counter", 0) + 1

                quotes_delta_payload = {}
                for sym, quote in chunk_quotes.items():
                    if quote.is_valid():
                        quotes_delta_payload[sym] = {
                            "price": _to_float(quote.price),
                            "previous_close": _to_float(quote.previous_close),
                            "status": quote.status.name if hasattr(quote.status, "name") else str(quote.status),
                            "quote_timestamp": quote.quote_timestamp.isoformat() if quote.quote_timestamp else None,
                        }

                batch_payload = {
                    "type": "batch",
                    "batch_index": batch_idx,
                    "total_batches": total_b,
                    "processed_symbols": _state["processed_symbols"],
                    "total_symbols": stale_count,
                    "updated": updated,
                    "failed": failed,
                    "batch_updated": batch_updated,
                    "batch_failed": batch_failed,
                    "quotes": quotes_delta_payload,
                }
                _broadcast_refresh_event(batch_payload)
                if on_batch_progress:
                    try:
                        on_batch_progress(batch_payload)
                    except Exception as ex:
                        logger.debug("Error in on_batch_progress (batch): %s", ex)

            runner = BatchRunner(provider=provider, batch_size=batch_size)
            runner.run(stale_symbols, on_batch_complete=on_batch_sqlite)

            result = {
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "total": total_symbols,
                "refreshed_count": updated,
                "stale_count": stale_count,
            }

            # Auto-resolve analysis reference prices
            try:
                analysis_res = _resolve_missing_analysis_prices_sync(user_id=user_id)
                if analysis_res.get("updated", 0) > 0:
                    result["analysis_prices_updated"] = analysis_res["updated"]
            except Exception as e:
                logger.warning("Could not auto-resolve missing analysis prices: %s", e)

            # Auto-resolve YTD reference prices
            try:
                ytd_res = _resolve_missing_ytd_prices_sync(user_id=user_id)
                if ytd_res.get("updated", 0) > 0:
                    result["ytd_prices_updated"] = ytd_res["updated"]
            except Exception as e:
                logger.warning("Could not auto-resolve missing YTD prices: %s", e)

            _update_state_on_completion(result, total_symbols)
            invalidate_positions_cache()

            complete_payload = {
                "type": "complete",
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "total": total_symbols,
                "refreshed_count": updated,
                "analysis_prices_updated": result.get("analysis_prices_updated", 0),
                "ytd_prices_updated": result.get("ytd_prices_updated", 0),
            }
            _broadcast_refresh_event(complete_payload, target_user_id=user_id)
            if on_batch_progress:
                try:
                    on_batch_progress(complete_payload)
                except Exception as ex:
                    logger.debug("Error in on_batch_progress (complete): %s", ex)

            return result

    except Exception as e:
        logger.error("Exception in refresh_all: %s", e)
        if is_multi_tenant_db() and 'run_id' in locals() and run_id:
            try:
                import portfoliomaster.db.session as db_session
                from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository
                with db_session.session_scope() as err_session:
                    r_repo = RefreshRunRepository(err_session)
                    r_repo.complete_run(
                        run_id=run_id,
                        status="FAILED",
                        error_message=str(e)[:500],
                    )
            except Exception:
                pass
        from portfoliomaster.db.session import is_production

        public_err = "Refresh failed due to an internal error." if is_production() else str(e)
        err_msg = f"error: {public_err}"
        with _state_lock:
            _state["last_refresh_result"] = err_msg
            _state["last_refresh_status"] = err_msg
        err_payload = {
            "type": "error",
            "detail": "Refresh failed due to an internal error." if is_production() else "Refresh failed.",
        }
        _broadcast_refresh_event(err_payload, target_user_id=user_id)
        if on_batch_progress:
            try:
                on_batch_progress(err_payload)
            except Exception:
                pass
        return {"status": "error", "detail": public_err}

    finally:
        with _state_lock:
            _state["is_refreshing"] = False
        lock.release()


@router.post("/refresh")
def trigger_refresh_all(
    force: bool = False,
    background: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Trigger a tenant-scoped watchlist quote refresh with per-user cooldown."""
    lock = _get_user_refresh_lock(user_id)
    if lock.locked():
        return {"status": "in_progress", "detail": "Refresh is already in progress."}

    if is_multi_tenant_db():
        import portfoliomaster.db.session as db_session
        from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository
        try:
            with db_session.session_scope() as session:
                run_repo = RefreshRunRepository(session)
                if run_repo.is_running(scope="USER", user_id=user_id):
                    return {"status": "in_progress", "detail": "Refresh is already in progress for this user."}
        except Exception as ex:
            logger.debug("Database refresh run check skipped: %s", ex)

    if background:
        t = threading.Thread(
            target=_execute_refresh_all,
            kwargs={"force": force, "user_id": user_id},
            daemon=True,
        )
        t.start()
        return {"status": "triggered"}

    return _execute_refresh_all(force=force, user_id=user_id)


@router.get("/refresh/stream")
async def refresh_stream(
    mode: Optional[str] = None,
    trigger: Optional[int] = None,
    force: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Pure read-only Server-Sent Events (SSE) subscriber endpoint scoped per tenant.

    Uses bounded asyncio.Queue(maxsize=100) without blocking worker threads and never triggers mutations.
    """
    is_listen_mode = (mode == "listen")

    allowed_symbols: Optional[frozenset[str]] = None
    if is_multi_tenant_db():
        def _load_allowed_symbols() -> frozenset[str]:
            import portfoliomaster.db.session as db_session
            from portfoliomaster.db.schema import UserInstrument
            from sqlalchemy import select
            with db_session.session_scope() as session:
                rows = session.execute(
                    select(UserInstrument.provider_symbol, UserInstrument.user_ticker).where(
                        UserInstrument.user_id == user_id,
                        UserInstrument.active.is_(True),
                    )
                ).all()
                return frozenset(
                    (ps or ut or "").strip().upper()
                    for ps, ut in rows
                    if (ps or ut or "").strip()
                )
        try:
            allowed_symbols = await asyncio.to_thread(_load_allowed_symbols)
        except Exception as ex:
            logger.debug("Could not load allowed SSE symbols: %s", ex)
            allowed_symbols = frozenset()

    async def event_generator():
        sub = _SSESubscriber(
            queue=asyncio.Queue(maxsize=100),
            loop=asyncio.get_running_loop(),
            user_id=user_id,
            allowed_symbols=allowed_symbols,
        )
        with _sse_lock:
            _sse_subscribers.add(sub)

        try:
            snapshot = get_refresh_state_snapshot()
            user_refreshing = _get_user_refresh_lock(user_id).locked() if is_multi_tenant_db() else bool(snapshot.get("is_refreshing"))
            connected = {
                "type": "connected",
                "is_refreshing": user_refreshing,
                "last_refresh_at": snapshot.get("last_refresh_at"),
                "refresh_counter": snapshot.get("refresh_counter", 0),
            }
            yield f"data: {json.dumps(connected)}\n\n"

            if user_refreshing:
                current_batch = snapshot.get("current_batch", 0)
                progress = {
                    "type": "batch" if current_batch > 0 else "start",
                    "batch_index": current_batch,
                    "total_batches": snapshot.get("total_batches", 0),
                    "processed_symbols": snapshot.get("processed_symbols", 0),
                    "total_symbols": snapshot.get("total_symbols", 0),
                }
                yield f"data: {json.dumps(progress)}\n\n"

            while True:
                try:
                    item = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                yield f"data: {json.dumps(item)}\n\n"
                if not is_listen_mode and item.get("type") in ("complete", "error"):
                    break
        finally:
            with _sse_lock:
                _sse_subscribers.discard(sub)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/instruments/{ticker}/refresh")
def refresh_single_instrument(
    ticker: str,
    force: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Refresh quote and missing reference prices for a single instrument with cooldown."""
    now_utc = datetime.now(timezone.utc)

    if is_multi_tenant_db():
        import portfoliomaster.db.session as db_session
        from portfoliomaster.db.multi_tenant_repository import (
            MultiTenantWatchlistRepository,
            GlobalMarketQuotesRepository,
        )
        from portfoliomaster.db.schema import UserInstrument
        from sqlalchemy import update

        # Phase 1: Read tenant instrument & quote cooldown in brief session
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

            inst_id = inst.id
            inst_ticker = inst.user_ticker
            symbol = (inst.provider_symbol or inst.user_ticker).strip().upper()
            inst_analysis_date = inst.analysis_date
            inst_analysis_price = inst.analysis_reference_price
            inst_soy_price = inst.start_of_year_price
            quote = inst.quote

            # Check individual cooldown (30s)
            if not force and quote and quote.last_attempt_at:
                last_ts = quote.last_attempt_at if quote.last_attempt_at.tzinfo else quote.last_attempt_at.replace(tzinfo=timezone.utc)
                elapsed = (now_utc - last_ts).total_seconds()
                if elapsed < STALE_THRESHOLD_SINGLE_SECONDS:
                    return {
                        "status": "fresh",
                        "message": f"Cotización de {ticker} actualizada recientemente",
                        "refreshed_count": 0,
                        "ticker": ticker,
                        "price": _to_float(quote.price),
                        "previous_close": _to_float(quote.previous_close),
                        "analysis_reference_price": _to_float(inst_analysis_price),
                        "start_of_year_price": _to_float(inst_soy_price),
                        "provider": quote.provider,
                        "quote_status": quote.status,
                        "quote": {
                            "price": _to_float(quote.price),
                            "previous_close": _to_float(quote.previous_close),
                            "status": quote.status,
                            "last_attempt_at": quote.last_attempt_at.isoformat() if quote.last_attempt_at else None,
                        },
                    }

        # Phase 2: Execute Yahoo Finance HTTP calls outside DB session
        adapter = _get_yahoo_adapter()
        quotes = adapter.fetch([symbol])
        if symbol not in quotes:
            raise HTTPException(status_code=502, detail=f"No response from Yahoo for '{symbol}'")

        fetched_q = quotes[symbol]
        resolved_analysis_price: Optional[Decimal] = None
        if inst_analysis_date and not inst_analysis_price:
            try:
                hist_p = _get_historical_quote_for_date(symbol, inst_analysis_date)
                if hist_p is not None:
                    resolved_analysis_price = Decimal(str(hist_p))
            except Exception as e:
                logger.debug("Error auto-resolving analysis price for %s: %s", ticker, e)

        resolved_soy_price: Optional[Decimal] = None
        resolved_soy_date: Optional[date] = None
        if not inst_soy_price:
            try:
                current_year = date.today().year
                res_ytd = _get_start_of_year_quote(symbol, current_year)
                if res_ytd:
                    p_val, actual_dt = res_ytd
                    resolved_soy_price = Decimal(str(p_val))
                    resolved_soy_date = actual_dt
            except Exception as e:
                logger.debug("Error auto-resolving YTD price for %s: %s", ticker, e)

        # Phase 3: Persist quote & resolved prices in brief session
        with db_session.session_scope() as session:
            quotes_repo = GlobalMarketQuotesRepository(session)
            status_str = fetched_q.status.name if hasattr(fetched_q.status, "name") else str(fetched_q.status)
            saved_quote = quotes_repo.upsert_market_quote_safe(
                provider_symbol=symbol,
                price=fetched_q.price,
                previous_close=fetched_q.previous_close,
                quote_timestamp=fetched_q.quote_timestamp,
                status=status_str,
                error_message=fetched_q.error_message,
                provider=fetched_q.provider or "yahoo",
            )

            inst_updates: dict = {}
            if resolved_analysis_price is not None:
                inst_updates["analysis_reference_price"] = resolved_analysis_price
            if resolved_soy_price is not None:
                inst_updates["start_of_year_price"] = resolved_soy_price
                inst_updates["start_of_year_date"] = resolved_soy_date
            if inst_updates:
                session.execute(
                    update(UserInstrument)
                    .where(UserInstrument.id == inst_id, UserInstrument.user_id == user_id)
                    .values(**inst_updates)
                )

            final_analysis_price = resolved_analysis_price if resolved_analysis_price is not None else inst_analysis_price
            final_soy_price = resolved_soy_price if resolved_soy_price is not None else inst_soy_price
            quote_payload = {
                "price": _to_float(saved_quote.price),
                "previous_close": _to_float(saved_quote.previous_close),
                "status": saved_quote.status,
                "last_attempt_at": saved_quote.last_attempt_at.isoformat() if saved_quote.last_attempt_at else None,
            }
            saved_price = _to_float(saved_quote.price)
            saved_prev = _to_float(saved_quote.previous_close)
            saved_provider = saved_quote.provider
            saved_status = saved_quote.status

        invalidate_positions_cache()
        return {
            "status": "ok",
            "ticker": inst_ticker,
            "price": saved_price,
            "previous_close": saved_prev,
            "analysis_reference_price": _to_float(final_analysis_price),
            "start_of_year_price": _to_float(final_soy_price),
            "provider": saved_provider,
            "quote_status": saved_status,
            "quote": quote_payload,
        }

    # SQLite mode
    inst = get_instrument_by_ticker(ticker)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

    symbol = inst.provider_symbol or inst.user_ticker
    saved_quote = get_quote_by_instrument_id(inst.id)

    # Check individual cooldown (30s)
    if not force and saved_quote and saved_quote.fetched_at:
        last_ts = saved_quote.fetched_at if saved_quote.fetched_at.tzinfo else saved_quote.fetched_at.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_ts).total_seconds()
        if elapsed < STALE_THRESHOLD_SINGLE_SECONDS:
            return {
                "status": "fresh",
                "message": f"Cotización de {ticker} actualizada recientemente",
                "refreshed_count": 0,
                "ticker": ticker,
                "price": _to_float(saved_quote.price),
                "previous_close": _to_float(saved_quote.previous_close),
                "analysis_reference_price": _to_float(inst.analysis_reference_price),
                "start_of_year_price": _to_float(inst.start_of_year_price),
                "provider": saved_quote.provider,
                "quote_status": saved_quote.status.name if hasattr(saved_quote.status, "name") else str(saved_quote.status),
                "quote": _quote_to_dict(saved_quote),
            }

    adapter = _get_yahoo_adapter()
    quotes = adapter.fetch([symbol])

    if symbol not in quotes:
        raise HTTPException(status_code=502, detail=f"No response from Yahoo for '{symbol}'")

    quote = quotes[symbol]
    quote.instrument_id = inst.id
    if quote.fetched_at is None:
        quote.fetched_at = datetime.now(timezone.utc)
    upsert_quote(quote)

    # Auto-resolve missing analysis reference price
    if inst.analysis_date and not inst.analysis_reference_price:
        try:
            hist_p = _get_historical_quote_for_date(symbol, inst.analysis_date)
            if hist_p is not None:
                inst.analysis_reference_price = Decimal(str(hist_p))
                update_instrument_by_id(inst)
        except Exception as e:
            logger.debug(f"Error auto-resolving analysis price for {ticker}: {e}")

    # Auto-resolve missing YTD price
    if not inst.start_of_year_price:
        try:
            current_year = date.today().year
            res_ytd = _get_start_of_year_quote(symbol, current_year)
            if res_ytd:
                p_val, actual_dt = res_ytd
                inst.start_of_year_price = Decimal(str(p_val))
                inst.start_of_year_date = actual_dt
                update_instrument_by_id(inst)
        except Exception as e:
            logger.debug(f"Error auto-resolving YTD price for {ticker}: {e}")

    invalidate_positions_cache()
    saved_quote = get_quote_by_instrument_id(inst.id)
    return {
        "status": "ok",
        "ticker": ticker,
        "price": _to_float(saved_quote.price) if saved_quote else None,
        "previous_close": _to_float(saved_quote.previous_close) if saved_quote else None,
        "analysis_reference_price": _to_float(inst.analysis_reference_price),
        "start_of_year_price": _to_float(inst.start_of_year_price),
        "provider": saved_quote.provider if saved_quote else None,
        "quote_status": saved_quote.status.name if (saved_quote and hasattr(saved_quote.status, "name")) else (str(saved_quote.status) if saved_quote else None),
        "quote": _quote_to_dict(saved_quote) if saved_quote else None,
    }
