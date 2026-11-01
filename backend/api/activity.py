"""Client activity and idle tracking for PortfolioMaster.

Gates background quote refresh cycles so that Render and Supabase do not
waste database bandwidth when no users are active or watching the application.
Excludes automated uptime probes, healthchecks, and CORS preflights.
"""

from __future__ import annotations

import threading
import time

_ACTIVITY_LOCK = threading.Lock()
_LAST_CLIENT_ACTIVITY_AT: float = time.time()

# Methods that do not represent active human client interactions
IGNORED_METHODS = frozenset({"OPTIONS", "HEAD"})

# Exact paths commonly probed by cloud platforms (Render, AWS, K8s, UptimeRobot)
IGNORED_EXACT_PATHS = frozenset({
    "",
    "/",
    "/health",
    "/healthcheck",
    "/api/health",
    "/api/healthcheck",
    "/healthz",
    "/ping",
    "/favicon.ico",
    "/robots.txt",
})

# Path prefixes for automated probes and documentation viewers
IGNORED_PREFIXES = (
    "/health",
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def should_ignore_request_for_activity(path: str, method: str = "GET") -> bool:
    """Check if an HTTP request should be ignored for idle client activity tracking.

    Returns True for:
    - HTTP methods OPTIONS (CORS preflight) and HEAD.
    - Healthcheck endpoints (/health, /healthcheck, /api/health, /healthz, /ping).
    - Root URL ('/') probed by uptime checkers.
    - OpenAPI and API documentation routes (/docs, /redoc, /openapi.json).
    - Browser metadata files (/favicon.ico, /robots.txt).
    """
    if method and method.upper() in IGNORED_METHODS:
        return True

    if not path:
        return True

    # Strip whitespace, query parameters, anchors, and normalize case
    clean_path = path.strip().split("?")[0].split("#")[0].lower()
    clean_path = clean_path.rstrip("/") if clean_path != "/" else "/"

    if not clean_path or clean_path in IGNORED_EXACT_PATHS:
        return True

    if clean_path.startswith(IGNORED_PREFIXES):
        return True

    return False


def record_client_activity() -> None:
    """Record that an active user request or SSE client interaction occurred."""
    global _LAST_CLIENT_ACTIVITY_AT
    with _ACTIVITY_LOCK:
        _LAST_CLIENT_ACTIVITY_AT = time.time()


def get_last_client_activity() -> float:
    """Return the timestamp (epoch seconds) of the most recent client activity."""
    with _ACTIVITY_LOCK:
        return _LAST_CLIENT_ACTIVITY_AT


def _set_last_client_activity(ts: float) -> None:
    """Set activity timestamp directly (useful for tests simulating idle periods)."""
    global _LAST_CLIENT_ACTIVITY_AT
    with _ACTIVITY_LOCK:
        _LAST_CLIENT_ACTIVITY_AT = ts


def reset_client_activity() -> None:
    """Reset activity timestamp to epoch 0.0 (idle state)."""
    global _LAST_CLIENT_ACTIVITY_AT
    with _ACTIVITY_LOCK:
        _LAST_CLIENT_ACTIVITY_AT = 0.0


def is_scheduler_idle(
    idle_timeout_seconds: float = 900.0,
    active_subscribers_count: int = 0,
) -> bool:
    """Determine whether the application is idle and background refreshes should pause.

    Returns False if:
    - At least one SSE subscriber is currently connected, or
    - Any client made an API request within the last `idle_timeout_seconds` (default: 15 minutes).

    Returns True if no clients are listening and no requests occurred for >15 minutes.
    """
    if active_subscribers_count > 0:
        return False

    with _ACTIVITY_LOCK:
        last_at = _LAST_CLIENT_ACTIVITY_AT

    if last_at <= 0.0:
        return True

    elapsed = time.time() - last_at
    return elapsed >= idle_timeout_seconds
