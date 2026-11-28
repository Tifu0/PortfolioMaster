"""Positions and metrics router for watchlistTracker (WT)."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response

from portfoliomaster.core.calculations import daily_variation
from portfoliomaster.core.parsing import safe_float
from portfoliomaster.db.ports import PortfolioStore

from ..common import get_current_user_id
from ..dependencies import get_portfolio_store
from ..services.cache import (
    _METRICS_CACHE,
    _POSITIONS_CACHE,
    cache_get,
    cache_set,
    generate_etag,
    get_cache_stats,
    invalidate_positions_cache,
    reset_cache_stats,
    respond_with_etag,
)

router = APIRouter(prefix="/api", tags=["positions"])


def _compute_metrics_summary(store: PortfolioStore) -> dict:
    """Compute portfolio summary KPIs directly from lightweight column projection."""
    rows_data = store.get_metrics_rows()
    total = len(rows_data)
    valid_daily: list[dict] = []

    for ticker, company, curr, latest_price, prev_close in rows_data:
        dv = daily_variation(latest_price, prev_close)
        if dv.daily_variation_valid and dv.daily_variation is not None:
            dv_float = safe_float(dv.daily_variation)
            if dv_float is not None:
                valid_daily.append(
                    {
                        "user_ticker": ticker,
                        "company_name": company,
                        "daily_variation": dv_float,
                        "latest_price": latest_price,
                        "currency": curr,
                    }
                )

    best = None
    worst = None
    avg_change = None
    positive_count = 0
    negative_count = 0
    neutral_count = 0

    if valid_daily:
        sorted_daily = sorted(valid_daily, key=lambda x: x["daily_variation"])
        worst = sorted_daily[0]
        best = sorted_daily[-1]

        total_change = 0.0
        for p in valid_daily:
            dv_val = p["daily_variation"]
            total_change += dv_val
            if dv_val > 0:
                positive_count += 1
            elif dv_val < 0:
                negative_count += 1
            else:
                neutral_count += 1

        avg_change = round(total_change / len(valid_daily), 2)

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


@router.get("/positions")
def get_positions(
    request: Request = None,
    response: Response = None,
    active_only: Optional[bool] = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Watchlist positions: instruments + quotes + server-computed columns."""
    cache_key = f"{user_id}:{active_only}"
    now = time.time()
    cached_entry = cache_get(_POSITIONS_CACHE, cache_key, now)
    if cached_entry:
        return respond_with_etag(cached_entry[0], cached_entry[1], request, response)

    positions = store.get_positions(active_only=active_only if active_only is not None else False)
    result = {"positions": positions, "count": len(positions)}

    etag = generate_etag(result)
    cache_set(_POSITIONS_CACHE, cache_key, result, etag, now)
    return respond_with_etag(result, etag, request, response)


@router.get("/metrics")
def get_metrics(
    request: Request = None,
    response: Response = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Summary KPI metrics: number of positions, top gainer/loser, average daily change."""
    cache_key = str(user_id)
    now = time.time()
    cached_entry = cache_get(_METRICS_CACHE, cache_key, now)
    if cached_entry:
        return respond_with_etag(cached_entry[0], cached_entry[1], request, response)

    result = _compute_metrics_summary(store)
    etag = generate_etag(result)
    cache_set(_METRICS_CACHE, cache_key, result, etag, now)
    return respond_with_etag(result, etag, request, response)


__all__ = [
    "_METRICS_CACHE",
    "_POSITIONS_CACHE",
    "get_cache_stats",
    "get_metrics",
    "get_positions",
    "invalidate_positions_cache",
    "reset_cache_stats",
    "router",
]
