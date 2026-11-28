"""Thread-safe bounded LRU+TTL in-memory cache for positions and metrics."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import threading
import uuid
from typing import Optional, Tuple

from fastapi import Request, Response

MAX_CACHE_ENTRIES = 256
CACHE_TTL_SECONDS = 60.0

_POSITIONS_CACHE: OrderedDict[str, Tuple[dict, str, float]] = OrderedDict()
_METRICS_CACHE: OrderedDict[str, Tuple[dict, str, float]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_STATS = {"hits": 0, "misses": 0}


def cache_get(
    cache: OrderedDict[str, Tuple[dict, str, float]], key: str, now: float
) -> Optional[Tuple[dict, str]]:
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


def cache_set(
    cache: OrderedDict[str, Tuple[dict, str, float]],
    key: str,
    result: dict,
    etag: str,
    now: float,
) -> None:
    """Insert or refresh entry in bounded LRU cache, evicting expired/oldest entries above MAX_CACHE_ENTRIES."""
    with _CACHE_LOCK:
        cache[key] = (result, etag, now)
        cache.move_to_end(key)
        expired = [k for k, (_, _, ts) in cache.items() if now - ts >= CACHE_TTL_SECONDS]
        for k in expired:
            cache.pop(k, None)
        while len(cache) > MAX_CACHE_ENTRIES:
            cache.popitem(last=False)


def generate_etag(payload: dict) -> str:
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
    """Thread-safe cache invalidation for a specific tenant or all tenants."""
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


def respond_with_etag(
    result: dict,
    etag: str,
    request: Optional[Request],
    response: Optional[Response],
):
    """Attach HTTP cache headers and return 304 Not Modified when ETag matches."""
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
