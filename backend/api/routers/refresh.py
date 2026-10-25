"""Batch refresh and live SSE streaming router for watchlistTracker (WT)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, TypedDict

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
    resolve_missing_analysis_prices,
    resolve_missing_ytd_prices,
)
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
_refresh_lock = threading.Lock()
_sse_subscribers: set[queue.Queue] = set()
_sse_lock = threading.Lock()


def _broadcast_refresh_event(payload: dict) -> None:
    """Thread-safe event broadcast to all connected SSE clients."""
    with _sse_lock:
        subscribers = list(_sse_subscribers)
    for q in subscribers:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def _update_state_on_completion(result: dict, total_symbols: int) -> None:
    """Helper to update internal _state dictionary consistently."""
    now_iso = datetime.now(timezone.utc).isoformat()
    _state["last_refresh_at"] = now_iso
    _state["last_refresh_time"] = now_iso
    _state["last_refresh_result"] = result
    status = result.get("status", "ok")
    updated = result.get("updated", 0)
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
) -> dict:
    """Core batch refresh engine with server cooldown and symbol deduplication."""
    acquired = _refresh_lock.acquire(blocking=False)
    if not acquired:
        return {"status": "in_progress", "detail": "Refresh is already in progress."}

    _state["is_refreshing"] = True
    _state["current_batch"] = 0
    _state["processed_symbols"] = 0

    try:
        now_utc = datetime.now(timezone.utc)

        if is_multi_tenant_db():
            from portfoliomaster.db.session import session_scope
            from portfoliomaster.db.schema import UserInstrument, MarketQuote
            from portfoliomaster.db.multi_tenant_repository import (
                GlobalMarketQuotesRepository,
                RefreshRunRepository,
            )
            from sqlalchemy import select

            with session_scope() as session:
                instruments = list(
                    session.scalars(
                        select(UserInstrument).where(UserInstrument.active.is_(True))
                    ).all()
                )
                total_inst = len(instruments)
                if total_inst == 0:
                    result = {
                        "status": "ok",
                        "updated": 0,
                        "failed": 0,
                        "total": 0,
                        "refreshed_count": 0,
                    }
                    _update_state_on_completion(result, 0)
                    return result

                # Map each symbol to instrument
                symbol_map: Dict[str, List[UserInstrument]] = {}
                for inst in instruments:
                    sym = (inst.provider_symbol or inst.user_ticker or "").strip().upper()
                    if sym:
                        symbol_map.setdefault(sym, []).append(inst)

                unique_symbols = list(symbol_map.keys())
                total_symbols = len(unique_symbols)

                # Fetch quotes for all unique symbols to evaluate staleness
                quotes_stmt = select(MarketQuote).where(MarketQuote.provider_symbol.in_(unique_symbols))
                existing_quotes = {q.provider_symbol: q for q in session.scalars(quotes_stmt).all()}

                stale_symbols: List[str] = []
                for sym in unique_symbols:
                    if force:
                        stale_symbols.append(sym)
                        continue
                    q = existing_quotes.get(sym)
                    if not q or q.last_attempt_at is None:
                        stale_symbols.append(sym)
                    else:
                        last_ts = q.last_attempt_at if q.last_attempt_at.tzinfo else q.last_attempt_at.replace(tzinfo=timezone.utc)
                        elapsed = (now_utc - last_ts).total_seconds()
                        if elapsed >= STALE_THRESHOLD_SECONDS:
                            stale_symbols.append(sym)

                # If no symbols are stale: return 'fresh' with HTTP 200 without network calls!
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

                # Multi-worker/instance coordination via PostgreSQL/DB refresh_runs
                run_repo = RefreshRunRepository(session)
                run_id = None

                # Clean up stale runs older than 10 minutes to prevent deadlocks from crashed workers
                cutoff = now_utc - timedelta(minutes=10)
                try:
                    from portfoliomaster.db.schema import RefreshRun
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
                        session.commit()
                except Exception as ex:
                    session.rollback()
                    logger.debug("Stale run check skipped: %s", ex)

                # Coordinate across instances: check if another worker is already RUNNING
                if run_repo.is_running(scope="GLOBAL"):
                    logger.info("[Refresh] Another refresh run is currently active in the database. Skipping duplicate execution.")
                    return {"status": "in_progress", "detail": "Refresh is already in progress across instances."}

                # Only fetch stale symbols!
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

                try:
                    run = run_repo.start_run(total_symbols=stale_count, trigger_type="batch_worker")
                    run_id = run.id
                    session.commit()
                except Exception as ex:
                    session.rollback()
                    logger.debug("Optional refresh_run record skipped: %s", ex)

                quotes_repo = GlobalMarketQuotesRepository(session)
                updated = 0
                failed = 0
                processed_count = 0

                def on_batch_pg(batch_idx: int, total_b: int, chunk_quotes: Dict[str, Quote]):
                    nonlocal updated, failed, processed_count
                    batch_updated = 0
                    batch_failed = 0

                    try:
                        for sym, quote in chunk_quotes.items():
                            status_str = quote.status.name if hasattr(quote.status, "name") else str(quote.status)
                            quotes_repo.upsert_market_quote_safe(
                                provider_symbol=sym,
                                price=quote.price,
                                previous_close=quote.previous_close,
                                quote_timestamp=quote.quote_timestamp,
                                status=status_str,
                                error_message=quote.error_message,
                                provider=quote.provider or "yahoo",
                            )
                            inst_list = symbol_map.get(sym, [])
                            if quote.is_valid():
                                updated += len(inst_list) if inst_list else 1
                                batch_updated += len(inst_list) if inst_list else 1
                            else:
                                failed += len(inst_list) if inst_list else 1
                                batch_failed += len(inst_list) if inst_list else 1
                            processed_count += 1

                        session.commit()
                        if run_id:
                            try:
                                run_repo.update_progress(
                                    run_id=run_id,
                                    processed=processed_count,
                                    successful=updated,
                                    failed=failed,
                                )
                                session.commit()
                            except Exception:
                                session.rollback()
                    except Exception as ex:
                        session.rollback()
                        logger.error(f"[Refresh] Error processing batch {batch_idx}: {ex}")
                        raise

                    _state["current_batch"] = batch_idx
                    _state["total_batches"] = total_b
                    _state["processed_symbols"] = min(processed_count, stale_count)
                    _state["total_symbols"] = stale_count
                    _state["refresh_counter"] = _state.get("refresh_counter", 0) + 1

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
                    }
                    _broadcast_refresh_event(batch_payload)
                    if on_batch_progress:
                        try:
                            on_batch_progress(batch_payload)
                        except Exception as ex:
                            logger.debug("Error in on_batch_progress (batch): %s", ex)

                runner = BatchRunner(provider=provider, batch_size=batch_size)
                runner.run(stale_symbols, on_batch_complete=on_batch_pg)

                if run_id:
                    try:
                        run_repo.complete_run(
                            run_id=run_id,
                            status="COMPLETED",
                            diagnostic_summary=f"Processed {processed_count} symbols: {updated} updated, {failed} failed.",
                        )
                        session.commit()
                    except Exception:
                        session.rollback()

                result = {
                    "status": "ok",
                    "updated": updated,
                    "failed": failed,
                    "total": total_symbols,
                    "refreshed_count": updated,
                    "stale_count": stale_count,
                }
                _update_state_on_completion(result, total_symbols)

                complete_payload = {
                    "type": "complete",
                    "status": "ok",
                    "updated": updated,
                    "failed": failed,
                    "total": total_symbols,
                    "refreshed_count": updated,
                }
                _broadcast_refresh_event(complete_payload)
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

                _state["current_batch"] = batch_idx
                _state["total_batches"] = total_b
                _state["processed_symbols"] = min(processed_count, stale_count)
                _state["total_symbols"] = stale_count
                _state["refresh_counter"] = _state.get("refresh_counter", 0) + 1

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
                analysis_res = resolve_missing_analysis_prices()
                if analysis_res.get("updated", 0) > 0:
                    result["analysis_prices_updated"] = analysis_res["updated"]
            except Exception as e:
                logger.warning("Could not auto-resolve missing analysis prices: %s", e)

            # Auto-resolve YTD reference prices
            try:
                ytd_res = resolve_missing_ytd_prices()
                if ytd_res.get("updated", 0) > 0:
                    result["ytd_prices_updated"] = ytd_res["updated"]
            except Exception as e:
                logger.warning("Could not auto-resolve missing YTD prices: %s", e)

            _update_state_on_completion(result, total_symbols)

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
            _broadcast_refresh_event(complete_payload)
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
                from portfoliomaster.db.session import session_scope
                from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository
                with session_scope() as err_session:
                    r_repo = RefreshRunRepository(err_session)
                    r_repo.complete_run(
                        run_id=run_id,
                        status="FAILED",
                        error_message=str(e)[:500],
                    )
                    err_session.commit()
            except Exception:
                pass
        err_msg = f"error: {e}"
        _state["last_refresh_result"] = err_msg
        _state["last_refresh_status"] = err_msg
        err_payload = {"type": "error", "detail": str(e)}
        _broadcast_refresh_event(err_payload)
        if on_batch_progress:
            try:
                on_batch_progress(err_payload)
            except Exception:
                pass
        return {"status": "error", "detail": str(e)}

    finally:
        _state["is_refreshing"] = False
        _refresh_lock.release()


@router.post("/refresh")
def trigger_refresh_all(
    force: bool = False,
    background: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Trigger a full watchlist quote refresh across all active instruments with server cooldown."""
    if _state["is_refreshing"]:
        return {"status": "in_progress", "detail": "Refresh is already in progress."}

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository
        try:
            with session_scope() as session:
                run_repo = RefreshRunRepository(session)
                if run_repo.is_running(scope="GLOBAL"):
                    return {"status": "in_progress", "detail": "Refresh is already in progress across instances."}
        except Exception as ex:
            logger.debug("Database refresh run check skipped: %s", ex)

    if background:
        t = threading.Thread(target=_execute_refresh_all, kwargs={"force": force}, daemon=True)
        t.start()
        return {"status": "triggered"}

    return _execute_refresh_all(force=force)


@router.get("/refresh/stream")
async def refresh_stream(
    mode: Optional[str] = None,
    trigger: Optional[int] = None,
    force: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Server-Sent Events (SSE) streaming endpoint for live progressive batch-by-batch quote refreshes.

    Modes:
    - mode="listen": Persistent SSE connection for live progressive updates across all background/manual refreshes.
    - default / trigger=1: Triggers a refresh (if not in progress) and streams events until completion.
    """
    is_listen_mode = (mode == "listen")

    async def event_generator():
        q: queue.Queue = queue.Queue()
        with _sse_lock:
            _sse_subscribers.add(q)

        # Yield connection confirmation immediately to unbuffer HTTP stream
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"

        if _state.get("is_refreshing"):
            cur_b = _state.get("current_batch", 0)
            tot_b = _state.get("total_batches", 0)
            proc = _state.get("processed_symbols", 0)
            tot_s = _state.get("total_symbols", 0)
            init_payload = {
                "type": "batch" if cur_b > 0 else "start",
                "batch_index": cur_b,
                "total_batches": tot_b,
                "processed_symbols": proc,
                "total_symbols": tot_s,
            }
            yield f"data: {json.dumps(init_payload)}\n\n"

        if not is_listen_mode and not _state.get("is_refreshing"):
            threading.Thread(target=_execute_refresh_all, kwargs={"force": force}, daemon=True).start()

        try:
            while True:
                try:
                    item = await asyncio.to_thread(q.get, timeout=1.0)
                except Exception:
                    yield ": keepalive\n\n"
                    continue

                yield f"data: {json.dumps(item)}\n\n"
                if not is_listen_mode and item.get("type") in ("complete", "error"):
                    break
        finally:
            with _sse_lock:
                _sse_subscribers.discard(q)

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
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.schema import UserInstrument, MarketQuote
        from portfoliomaster.db.multi_tenant_repository import (
            MultiTenantWatchlistRepository,
            GlobalMarketQuotesRepository,
        )

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")

            symbol = (inst.provider_symbol or inst.user_ticker).strip().upper()
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
                        "analysis_reference_price": _to_float(inst.analysis_reference_price),
                        "start_of_year_price": _to_float(inst.start_of_year_price),
                        "provider": quote.provider,
                        "quote_status": quote.status,
                        "quote": {
                            "price": _to_float(quote.price),
                            "previous_close": _to_float(quote.previous_close),
                            "status": quote.status,
                            "last_attempt_at": quote.last_attempt_at.isoformat() if quote.last_attempt_at else None,
                        },
                    }

            adapter = _get_yahoo_adapter()
            quotes = adapter.fetch([symbol])
            if symbol not in quotes:
                raise HTTPException(status_code=502, detail=f"No response from Yahoo for '{symbol}'")

            fetched_q = quotes[symbol]
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
            session.commit()

            # Auto-resolve missing analysis reference price
            if inst.analysis_date and not inst.analysis_reference_price:
                try:
                    hist_p = _get_historical_quote_for_date(symbol, inst.analysis_date)
                    if hist_p is not None:
                        inst.analysis_reference_price = Decimal(str(hist_p))
                        session.commit()
                except Exception as e:
                    logger.debug("Error auto-resolving analysis price for %s: %s", ticker, e)

            # Auto-resolve missing YTD price
            if not inst.start_of_year_price:
                try:
                    current_year = date.today().year
                    res_ytd = _get_start_of_year_quote(symbol, current_year)
                    if res_ytd:
                        p_val, actual_dt = res_ytd
                        inst.start_of_year_price = Decimal(str(p_val))
                        inst.start_of_year_date = actual_dt
                        session.commit()
                except Exception as e:
                    logger.debug("Error auto-resolving YTD price for %s: %s", ticker, e)

            return {
                "status": "ok",
                "ticker": ticker,
                "price": _to_float(saved_quote.price),
                "previous_close": _to_float(saved_quote.previous_close),
                "analysis_reference_price": _to_float(inst.analysis_reference_price),
                "start_of_year_price": _to_float(inst.start_of_year_price),
                "provider": saved_quote.provider,
                "quote_status": saved_quote.status,
                "quote": {
                    "price": _to_float(saved_quote.price),
                    "previous_close": _to_float(saved_quote.previous_close),
                    "status": saved_quote.status,
                    "last_attempt_at": saved_quote.last_attempt_at.isoformat() if saved_quote.last_attempt_at else None,
                },
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
