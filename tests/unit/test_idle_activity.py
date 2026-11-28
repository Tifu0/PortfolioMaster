"""Unit and middleware tests for idle-aware background refresh scheduler gating."""

import time

from backend.api.activity import (
    _set_last_client_activity,
    get_last_client_activity,
    is_scheduler_idle,
    record_client_activity,
    reset_client_activity,
    should_ignore_request_for_activity,
)


def test_idle_detection_after_15_minutes():
    reset_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is True

    record_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is False

    _set_last_client_activity(time.time() - 905)
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is True
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=1) is False

    record_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is False


def test_should_ignore_request_for_activity_rules():
    assert should_ignore_request_for_activity("/api/positions", "OPTIONS") is True
    assert should_ignore_request_for_activity("/api/positions", "options") is True
    assert should_ignore_request_for_activity("/health", "HEAD") is True
    assert should_ignore_request_for_activity("/", "head") is True

    for path in ("/health", "/health/", "/HEALTH", "/healthcheck", "/api/health", "/api/healthcheck", "/healthz", "/ping", "/", "", "/docs", "/docs/", "/redoc", "/openapi.json", "/favicon.ico", "/robots.txt"):
        assert should_ignore_request_for_activity(path, "GET") is True

    for path, method in (
        ("/api/positions", "GET"),
        ("/api/metrics", "GET"),
        ("/api/instruments", "POST"),
        ("/api/refresh", "POST"),
        ("/api/refresh/stream", "GET"),
    ):
        assert should_ignore_request_for_activity(path, method) is False


def test_activity_middleware_ignores_healthchecks_and_options_end_to_end(sqlite_api_client):
    reset_client_activity()
    assert get_last_client_activity() == 0.0

    for path in ("/health", "/healthcheck", "/", "/docs", "/openapi.json"):
        res = sqlite_api_client.get(path)
        assert res.status_code == 200
        assert get_last_client_activity() == 0.0

    res = sqlite_api_client.options(
        "/api/positions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0

    res_405 = sqlite_api_client.options("/api/positions")
    assert res_405.status_code == 405
    assert get_last_client_activity() == 0.0

    assert sqlite_api_client.head("/health").status_code == 200
    assert get_last_client_activity() == 0.0

    assert sqlite_api_client.get("/api/positions").status_code == 200
    assert get_last_client_activity() > 0.0
