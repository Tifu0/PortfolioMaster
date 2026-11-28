"""Tenant-scoped SSE broker and thread-safe refresh state tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, TypedDict

from fastapi.responses import StreamingResponse

from portfoliomaster.db.ports import PortfolioStore

logger = logging.getLogger(__name__)


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


@dataclass(eq=False)
class SSESubscriber:
    """Tenant-scoped non-blocking SSE subscriber backed by bounded asyncio.Queue."""

    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop
    user_id: uuid.UUID
    allowed_symbols: Optional[frozenset[str]] = field(default=None)


_sse_subscribers: set[SSESubscriber] = set()
_sse_lock = threading.Lock()


def get_refresh_state_snapshot() -> RefreshStateDict:
    """Return a thread-safe shallow copy of the refresh state dictionary."""
    with _state_lock:
        return dict(_state)


def get_active_sse_subscribers_count() -> int:
    """Return the number of connected SSE subscriber queues."""
    with _sse_lock:
        return len(_sse_subscribers)


def mark_refresh_started() -> None:
    """Initialize state counters atomically when a refresh run starts."""
    with _state_lock:
        _state["is_refreshing"] = True
        _state["current_batch"] = 0
        _state["processed_symbols"] = 0


def set_refresh_plan(stale_count: int, total_batches: int) -> None:
    """Record batch plan totals before executing Yahoo chunks."""
    with _state_lock:
        _state["current_batch"] = 0
        _state["total_batches"] = total_batches
        _state["processed_symbols"] = 0
        _state["total_symbols"] = stale_count


def update_state_on_batch(
    batch_idx: int, total_batches: int, processed_count: int, stale_count: int
) -> int:
    """Update shared batch progress counters under _state_lock and return bounded processed count."""
    with _state_lock:
        _state["current_batch"] = batch_idx
        _state["total_batches"] = total_batches
        _state["processed_symbols"] = min(processed_count, stale_count)
        _state["total_symbols"] = stale_count
        _state["refresh_counter"] = _state.get("refresh_counter", 0) + 1
        return _state["processed_symbols"]


def update_state_on_completion(result: dict, total_symbols: int) -> None:
    """Update internal _state dictionary consistently upon completion or cooldown hit."""
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


def mark_refresh_error(err_msg: str) -> None:
    """Record refresh failure summary under lock."""
    with _state_lock:
        _state["last_refresh_result"] = err_msg
        _state["last_refresh_status"] = err_msg


def mark_refresh_finished() -> None:
    """Clear the active refreshing flag under lock."""
    with _state_lock:
        _state["is_refreshing"] = False


def enqueue_nonblocking(q: asyncio.Queue, item: dict) -> None:
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


def filter_payload_for_subscriber(
    payload: dict,
    sub: SSESubscriber,
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


def broadcast_refresh_event(
    payload: dict,
    target_user_id: Optional[uuid.UUID] = None,
    subscribers_set: Optional[set[SSESubscriber]] = None,
    subscribers_lock: Optional[threading.Lock] = None,
) -> None:
    """Thread-safe event broadcast to matching tenant SSE clients via asyncio.Queue."""
    if payload.get("type") == "complete":
        with _state_lock:
            payload = {
                **payload,
                "last_refresh_at": _state["last_refresh_at"],
                "refresh_counter": _state["refresh_counter"],
            }
    subs = subscribers_set if subscribers_set is not None else _sse_subscribers
    lock = subscribers_lock if subscribers_lock is not None else _sse_lock
    with lock:
        subscribers = list(subs)
    for sub in subscribers:
        filtered = filter_payload_for_subscriber(payload, sub, target_user_id)
        if filtered is None:
            continue
        try:
            if not sub.loop.is_closed():
                sub.loop.call_soon_threadsafe(enqueue_nonblocking, sub.queue, filtered)
        except RuntimeError:
            pass


async def stream_refresh_events(
    user_id: uuid.UUID,
    store: PortfolioStore,
    is_listen_mode: bool,
    *,
    is_user_refreshing_fn: Callable[[uuid.UUID, bool], bool],
    subscribers_set: Optional[set[SSESubscriber]] = None,
    subscribers_lock: Optional[threading.Lock] = None,
) -> StreamingResponse:
    """Build a pure read-only StreamingResponse SSE generator scoped per tenant."""
    allowed_symbols: Optional[frozenset[str]] = None
    if not store.supports_sqlite_file_backups:
        try:
            allowed_symbols = await asyncio.to_thread(store.list_active_symbols)
        except Exception as ex:
            logger.debug("Could not load allowed SSE symbols: %s", ex)
            allowed_symbols = frozenset()

    subs = subscribers_set if subscribers_set is not None else _sse_subscribers
    lock = subscribers_lock if subscribers_lock is not None else _sse_lock

    async def event_generator():
        sub = SSESubscriber(
            queue=asyncio.Queue(maxsize=100),
            loop=asyncio.get_running_loop(),
            user_id=user_id,
            allowed_symbols=allowed_symbols,
        )
        with lock:
            subs.add(sub)

        try:
            snapshot = get_refresh_state_snapshot()
            user_refreshing = is_user_refreshing_fn(user_id, not store.supports_sqlite_file_backups)
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
            with lock:
                subs.discard(sub)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
