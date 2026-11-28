"""Batch refresh and live SSE streaming router for watchlistTracker (WT)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Callable, Optional

from fastapi import APIRouter, Depends

from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.providers.yahoo_adapter import YahooAdapter

from ..common import get_current_user_id
from ..dependencies import (
    get_portfolio_store,
    get_system_portfolio_store,
    get_yahoo_provider,
)
from ..services import refresh_coordinator, refresh_sse
from .instruments import (
    _fetch_historical_quote_for_date,
    _fetch_start_of_year_quote,
    _resolve_missing_analysis_prices_sync,
    _resolve_missing_ytd_prices_sync,
)

router = APIRouter(prefix="/api", tags=["refresh"])

STALE_THRESHOLD_SECONDS = refresh_coordinator.STALE_THRESHOLD_SECONDS
STALE_THRESHOLD_SINGLE_SECONDS = refresh_coordinator.STALE_THRESHOLD_SINGLE_SECONDS

_state = refresh_sse._state
_state_lock = refresh_sse._state_lock
_SSESubscriber = refresh_sse.SSESubscriber
_sse_subscribers = refresh_sse._sse_subscribers
_sse_lock = refresh_sse._sse_lock
get_refresh_state_snapshot = refresh_sse.get_refresh_state_snapshot


def _get_active_sse_subscribers_count() -> int:
    """Return the number of active SSE subscriber queues."""
    with _sse_lock:
        return len(_sse_subscribers)


def _get_yahoo_adapter() -> YahooAdapter:
    return get_yahoo_provider()


_ORIG_GET_YAHOO_ADAPTER = _get_yahoo_adapter


def _get_historical_quote_for_date(provider_symbol: str, target_date: date) -> Optional[float]:
    return _fetch_historical_quote_for_date(provider_symbol, target_date)


def _get_start_of_year_quote(
    provider_symbol: str, year: Optional[int] = None
) -> Optional[tuple[float, date]]:
    return _fetch_start_of_year_quote(provider_symbol, year)


def _broadcast_refresh_event(
    payload: dict, target_user_id: Optional[uuid.UUID] = None
) -> None:
    refresh_sse.broadcast_refresh_event(
        payload,
        target_user_id=target_user_id,
        subscribers_set=_sse_subscribers,
        subscribers_lock=_sse_lock,
    )


def _execute_refresh_all(
    on_batch_progress: Optional[Callable[[dict], None]] = None,
    force: bool = False,
    user_id: Optional[uuid.UUID] = None,
    store: Optional[PortfolioStore] = None,
    provider: Optional[YahooAdapter] = None,
) -> dict:
    """Delegate batch refresh to refresh_coordinator using DI-resolved store and provider."""
    active_store = store or (
        get_portfolio_store(user_id=user_id)
        if user_id is not None
        else get_system_portfolio_store()
    )
    active_provider = provider if _get_yahoo_adapter is _ORIG_GET_YAHOO_ADAPTER and provider is not None else _get_yahoo_adapter()
    return refresh_coordinator.execute_refresh_all(
        active_store,
        active_provider,
        on_batch_progress=on_batch_progress,
        force=force,
        user_id=user_id,
        stale_threshold_seconds=STALE_THRESHOLD_SECONDS,
        broadcast_fn=_broadcast_refresh_event,
        resolve_analysis_fn=_resolve_missing_analysis_prices_sync,
        resolve_ytd_fn=_resolve_missing_ytd_prices_sync,
    )


@router.post("/refresh")
def trigger_refresh_all(
    force: bool = False,
    background: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Trigger a tenant-scoped watchlist quote refresh with per-user cooldown."""
    active_provider = provider if _get_yahoo_adapter is _ORIG_GET_YAHOO_ADAPTER else _get_yahoo_adapter()
    return refresh_coordinator.trigger_refresh(
        force=force,
        background=background,
        user_id=user_id,
        store=store,
        provider=active_provider,
        execute_fn=lambda **kw: _execute_refresh_all(store=store, provider=active_provider, **kw),
    )


@router.get("/refresh/stream")
async def refresh_stream(
    mode: Optional[str] = None,
    trigger: Optional[int] = None,
    force: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Pure read-only Server-Sent Events (SSE) subscriber endpoint scoped per tenant."""
    active_store = store if isinstance(store, PortfolioStore) else get_portfolio_store(user_id=user_id)
    return await refresh_sse.stream_refresh_events(
        user_id=user_id,
        store=active_store,
        is_listen_mode=(mode == "listen"),
        is_user_refreshing_fn=refresh_coordinator.is_user_refreshing,
        subscribers_set=_sse_subscribers,
        subscribers_lock=_sse_lock,
    )


@router.post("/instruments/{ticker}/refresh")
def refresh_single_instrument(
    ticker: str,
    force: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Refresh quote and missing reference prices for a single instrument with cooldown."""
    active_provider = provider if _get_yahoo_adapter is _ORIG_GET_YAHOO_ADAPTER else _get_yahoo_adapter()
    return refresh_coordinator.refresh_single_instrument(
        ticker,
        force=force,
        user_id=user_id,
        store=store,
        provider=active_provider,
        single_cooldown_seconds=STALE_THRESHOLD_SINGLE_SECONDS,
        hist_scalar_fn=_get_historical_quote_for_date,
        soy_fn=_get_start_of_year_quote,
    )
