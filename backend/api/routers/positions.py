"""Positions and metrics router for watchlistTracker (WT)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import Dict, Optional, Tuple
from fastapi import APIRouter, Depends, Query, Request, Response
import pandas as pd

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

# Thread-safe in-memory cache for positions and metrics
# Maps cache_key -> (payload_dict, etag_str, timestamp_float)
_POSITIONS_CACHE: Dict[str, Tuple[dict, str, float]] = {}
_METRICS_CACHE: Dict[str, Tuple[dict, str, float]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_STATS = {"hits": 0, "misses": 0}
CACHE_TTL_SECONDS = 60.0


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
    cached_entry = None

    with _CACHE_LOCK:
        if cache_key in _POSITIONS_CACHE:
            entry_data, entry_etag, entry_ts = _POSITIONS_CACHE[cache_key]
            if now - entry_ts < CACHE_TTL_SECONDS:
                _CACHE_STATS["hits"] += 1
                cached_entry = (entry_data, entry_etag)
            else:
                _POSITIONS_CACHE.pop(cache_key, None)

    if cached_entry:
        data, etag = cached_entry
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
        return data

    with _CACHE_LOCK:
        _CACHE_STATS["misses"] += 1

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
            df = pd.read_sql_query(query, conn)
        finally:
            conn.close()

        positions = []
        for _, row in df.iterrows():
            latest_price = _to_float(row.get("latest_price"))
            prev_close = _to_float(row.get("previous_close"))
            analysis_ref = _to_float(row.get("analysis_reference_price"))
            start_of_year_price = _to_float(row.get("start_of_year_price"))
            target = _to_float(row.get("target_price"))

            dv = daily_variation(latest_price, prev_close)
            vsa = variation_since_analysis(latest_price, analysis_ref)
            ytd = ytd_variation(latest_price, start_of_year_price)
            dtt = decline_to_target(target, latest_price)

            analysis_date_raw = row.get("analysis_date")
            analysis_date_str = None
            if analysis_date_raw is not None and not pd.isna(analysis_date_raw):
                analysis_date_str = str(analysis_date_raw)

            start_of_year_date_raw = row.get("start_of_year_date")
            start_of_year_date_str = None
            if start_of_year_date_raw is not None and not pd.isna(start_of_year_date_raw):
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
                    "latest_price": latest_price,
                    "previous_close": prev_close,
                    "quote_status": _clean_opt_str(row.get("quote_status")),
                    "quote_provider": _clean_opt_str(row.get("quote_provider")),
                    "quote_fetched_at": _clean_opt_str(row.get("quote_fetched_at")),
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
    with _CACHE_LOCK:
        _POSITIONS_CACHE[cache_key] = (result, etag, now)

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


@router.get("/metrics")
def get_metrics(
    request: Request = None,
    response: Response = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Summary KPI metrics: number of positions, top gainer/loser, average daily change."""
    cache_key = str(user_id)
    now = time.time()
    cached_entry = None

    with _CACHE_LOCK:
        if cache_key in _METRICS_CACHE:
            entry_data, entry_etag, entry_ts = _METRICS_CACHE[cache_key]
            if now - entry_ts < CACHE_TTL_SECONDS:
                _CACHE_STATS["hits"] += 1
                cached_entry = (entry_data, entry_etag)
            else:
                _METRICS_CACHE.pop(cache_key, None)

    if cached_entry:
        data, etag = cached_entry
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
        return data

    with _CACHE_LOCK:
        _CACHE_STATS["misses"] += 1

    pos_res = get_positions(user_id=user_id)
    if isinstance(pos_res, Response):
        pos_data = []
    else:
        pos_data = pos_res.get("positions", [])

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

    result = {
        "total_positions": total,
        "positions_with_quotes": len(valid_daily),
        "best_performer": best,
        "worst_performer": worst,
        "average_daily_change": avg_change,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
    }

    etag = _generate_etag(result)
    with _CACHE_LOCK:
        _METRICS_CACHE[cache_key] = (result, etag, now)

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
