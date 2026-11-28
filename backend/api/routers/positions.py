"""Positions and metrics router for watchlistTracker (WT)."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, Query, Request, Response

from portfoliomaster.core.calculations import (
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)
from portfoliomaster.db.connection import get_connection
from ..common import (
    _clean_opt_str,
    _clean_str,
    _to_float,
    get_current_user_id,
    is_multi_tenant_db,
)

router = APIRouter(prefix="/api", tags=["positions"])

# Thread-safe bounded LRU+TTL in-memory cache for positions and metrics
# Maps cache_key -> (payload_dict, etag_str, timestamp_float)
MAX_CACHE_ENTRIES = 256
_POSITIONS_CACHE: OrderedDict[str, Tuple[dict, str, float]] = OrderedDict()
_METRICS_CACHE: OrderedDict[str, Tuple[dict, str, float]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_STATS = {"hits": 0, "misses": 0}
CACHE_TTL_SECONDS = 60.0


def _cache_get(cache: OrderedDict[str, Tuple[dict, str, float]], key: str, now: float) -> Optional[Tuple[dict, str]]:
    """Retrieve non-expired entry from bounded LRU cache under lock."""
    with _CACHE_LOCK:
        entry = cache.get(key)
        if entry is not None:
            entry_data, entry_etag, entry_ts = entry
            if now - entry_ts < CACHE_TTL_SECONDS:
                cache.move_to_end(key)
                _CACHE_STATS["hits"] += 1
                return entry_data, entry_etag
            cache.pop(key, None)
        _CACHE_STATS["misses"] += 1
    return None


def _cache_set(cache: OrderedDict[str, Tuple[dict, str, float]], key: str, result: dict, etag: str, now: float) -> None:
    """Insert or refresh entry in bounded LRU cache, evicting expired/oldest entries above MAX_CACHE_ENTRIES."""
    with _CACHE_LOCK:
        cache[key] = (result, etag, now)
        cache.move_to_end(key)
        expired = [k for k, (_, _, ts) in cache.items() if now - ts >= CACHE_TTL_SECONDS]
        for k in expired:
            cache.pop(k, None)
        while len(cache) > MAX_CACHE_ENTRIES:
            cache.popitem(last=False)


def _generate_etag(payload: dict) -> str:
    """Generate deterministic strong ETag from serialised dictionary."""
    serialized = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f'"{digest}"'


def get_cache_stats() -> dict[str, int]:
    """Retrieve hit/miss statistics for test inspection and telemetry."""
    with _CACHE_LOCK:
        return dict(_CACHE_STATS)


def reset_cache_stats() -> None:
    """Reset hit/miss statistics to zero."""
    with _CACHE_LOCK:
        _CACHE_STATS["hits"] = 0
        _CACHE_STATS["misses"] = 0


def invalidate_positions_cache(user_id: Optional[uuid.UUID | str] = None) -> None:
    """Safe thread-safe cache invalidation hook.

    If user_id is provided, invalidates for that specific user.
    If user_id is None, invalidates all cached positions and metrics.
    """
    with _CACHE_LOCK:
        if user_id is None:
            _POSITIONS_CACHE.clear()
            _METRICS_CACHE.clear()
        else:
            uid_str = str(user_id)
            for k in list(_POSITIONS_CACHE.keys()):
                if k.startswith(uid_str):
                    _POSITIONS_CACHE.pop(k, None)
            for k in list(_METRICS_CACHE.keys()):
                if k.startswith(uid_str):
                    _METRICS_CACHE.pop(k, None)


def _respond_with_etag(
    result: dict,
    etag: str,
    request: Optional[Request],
    response: Optional[Response],
):
    if response is not None:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "private, no-cache, must-revalidate"
    if request is not None:
        client_etag = request.headers.get("if-none-match")
        if client_etag and client_etag.strip() == etag:
            return Response(
                status_code=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": "private, no-cache, must-revalidate",
                },
            )
    return result


@router.get("/positions")
def get_positions(
    request: Request = None,
    response: Response = None,
    active_only: Optional[bool] = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Watchlist positions: instruments + quotes + server-computed columns.
    
    If active_only is True, returns only active instruments.
    If active_only is False or omitted, returns all instruments for backward compatibility.
    """
    cache_key = f"{user_id}:{active_only}"
    now = time.time()
    cached_entry = _cache_get(_POSITIONS_CACHE, cache_key, now)
    if cached_entry:
        return _respond_with_etag(cached_entry[0], cached_entry[1], request, response)

    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.multi_tenant_repository import MultiTenantWatchlistRepository

        with session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, user_id)
            positions = repo.get_positions_with_calculations(
                active_only=active_only if active_only is not None else False
            )
            result = {"positions": positions, "count": len(positions)}
    else:
        conn = get_connection()
        try:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT
                    i.*,
                    q.price          AS latest_price,
                    q.previous_close AS previous_close,
                    q.status         AS quote_status,
                    q.provider       AS quote_provider,
                    q.fetched_at     AS quote_fetched_at
                FROM instruments i
                LEFT JOIN quotes q ON q.instrument_id = i.id
            """
            if active_only is True:
                query += " WHERE i.active = 1"
            rows = conn.execute(query).fetchall()
        finally:
            conn.close()

        positions = []
        for row in rows:
            latest_price = _to_float(row["latest_price"])
            prev_close = _to_float(row["previous_close"])
            analysis_ref = _to_float(row["analysis_reference_price"])
            start_of_year_price = _to_float(row["start_of_year_price"])
            target = _to_float(row["target_price"])

            dv = daily_variation(latest_price, prev_close)
            vsa = variation_since_analysis(latest_price, analysis_ref)
            ytd = ytd_variation(latest_price, start_of_year_price)
            dtt = decline_to_target(target, latest_price)

            analysis_date_raw = row["analysis_date"]
            analysis_date_str = str(analysis_date_raw) if analysis_date_raw is not None else None

            start_of_year_date_raw = row["start_of_year_date"]
            start_of_year_date_str = str(start_of_year_date_raw) if start_of_year_date_raw is not None else None

            row_id = row["id"]
            try:
                row_id_int = int(row_id) if row_id is not None else None
            except (TypeError, ValueError):
                row_id_int = None

            row_active = row["active"]
            active_bool = bool(row_active) if row_active is not None else True

            positions.append(
                {
                    "id": row_id_int,
                    "user_ticker": _clean_str(row["user_ticker"]),
                    "provider_symbol": _clean_opt_str(row["provider_symbol"]),
                    "exchange": _clean_str(row["exchange"]),
                    "currency": _clean_str(row["currency"]),
                    "company_name": _clean_str(row["company_name"]),
                    "analysis_date": analysis_date_str,
                    "analysis_reference_price": analysis_ref,
                    "start_of_year_date": start_of_year_date_str,
                    "start_of_year_price": start_of_year_price,
                    "target_price": target,
                    "comment": _clean_str(row["comment"]),
                    "active": active_bool,
                    "latest_price": latest_price,
                    "previous_close": prev_close,
                    "quote_status": _clean_opt_str(row["quote_status"]),
                    "quote_provider": _clean_opt_str(row["quote_provider"]),
                    "quote_fetched_at": _clean_opt_str(row["quote_fetched_at"]),
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

        result = {"positions": positions, "count": len(positions)}

    etag = _generate_etag(result)
    _cache_set(_POSITIONS_CACHE, cache_key, result, etag, now)
    return _respond_with_etag(result, etag, request, response)


def _compute_metrics_summary(user_id: uuid.UUID) -> dict:
    """Compute portfolio summary KPIs directly from lightweight column projection."""
    rows_data: list[tuple[str, str, str, Optional[float], Optional[float]]] = []

    if is_multi_tenant_db():
        from sqlalchemy import select
        from portfoliomaster.db.session import session_scope
        from portfoliomaster.db.schema import MarketQuote, UserInstrument

        with session_scope() as session:
            stmt = (
                select(
                    UserInstrument.user_ticker,
                    UserInstrument.company_name,
                    UserInstrument.currency,
                    MarketQuote.price,
                    MarketQuote.previous_close,
                )
                .outerjoin(
                    MarketQuote,
                    UserInstrument.provider_symbol == MarketQuote.provider_symbol,
                )
                .where(UserInstrument.user_id == user_id)
            )
            for ticker, company, curr, price, prev_close in session.execute(stmt).all():
                rows_data.append(
                    (
                        ticker,
                        company or ticker,
                        curr or "EUR",
                        float(price) if price is not None else None,
                        float(prev_close) if prev_close is not None else None,
                    )
                )
    else:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT
                    i.user_ticker,
                    i.company_name,
                    i.currency,
                    q.price AS latest_price,
                    q.previous_close AS previous_close
                FROM instruments i
                LEFT JOIN quotes q ON q.instrument_id = i.id
                """
            ).fetchall()
        finally:
            conn.close()
        for ticker, company, curr, latest_price, prev_close in rows:
            rows_data.append(
                (
                    _clean_str(ticker),
                    _clean_str(company) or _clean_str(ticker),
                    _clean_str(curr),
                    _to_float(latest_price),
                    _to_float(prev_close),
                )
            )

    total = len(rows_data)
    valid_daily: list[dict] = []
    for ticker, company, curr, latest_price, prev_close in rows_data:
        dv = daily_variation(latest_price, prev_close)
        if dv.daily_variation_valid and dv.daily_variation is not None:
            dv_float = _to_float(dv.daily_variation)
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


@router.get("/metrics")
def get_metrics(
    request: Request = None,
    response: Response = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Summary KPI metrics: number of positions, top gainer/loser, average daily change."""
    cache_key = str(user_id)
    now = time.time()
    cached_entry = _cache_get(_METRICS_CACHE, cache_key, now)
    if cached_entry:
        return _respond_with_etag(cached_entry[0], cached_entry[1], request, response)

    result = _compute_metrics_summary(user_id)
    etag = _generate_etag(result)
    _cache_set(_METRICS_CACHE, cache_key, result, etag, now)
    return _respond_with_etag(result, etag, request, response)
