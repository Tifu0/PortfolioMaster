"""Unit tests for idle-aware background refresh scheduler gating."""

import time
import uuid
import jwt
from fastapi.testclient import TestClient

from backend.api.activity import (
    get_last_client_activity,
    is_scheduler_idle,
    record_client_activity,
    reset_client_activity,
    should_ignore_request_for_activity,
    _set_last_client_activity,
)
from backend.api.main import app

TEST_USER_ID = uuid.UUID("c6dd2d21-c378-40f4-9848-5680db9fec27")
TEST_JWT_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"


def _mint_test_token(user_id: uuid.UUID = TEST_USER_ID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "role": "authenticated"},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def test_idle_detection_after_15_minutes():
    """Verify that scheduler is flagged as idle after 15 minutes of inactivity when 0 SSE subscribers exist."""
    reset_client_activity()
    # At initial state (timestamp is 0.0), it is idle
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is True

    # When client activity is recorded, it becomes active
    record_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is False

    # Simulate past timestamp: 905 seconds ago (> 15 minutes)
    _set_last_client_activity(time.time() - 905)
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is True

    # Even if time > 15m, if an SSE subscriber is active, scheduler is NOT idle
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=1) is False

    # Instant wake-up: client activity immediately resets idle flag
    record_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900, active_subscribers_count=0) is False


def test_should_ignore_request_for_activity_rules():
    """Verify unit-level filtering of automated health probes, docs, and CORS preflights."""
    # HTTP Methods
    assert should_ignore_request_for_activity("/api/positions", "OPTIONS") is True
    assert should_ignore_request_for_activity("/api/positions", "options") is True
    assert should_ignore_request_for_activity("/health", "HEAD") is True
    assert should_ignore_request_for_activity("/", "head") is True

    # Healthcheck endpoints and variants
    assert should_ignore_request_for_activity("/health", "GET") is True
    assert should_ignore_request_for_activity("/health/", "GET") is True
    assert should_ignore_request_for_activity("/HEALTH", "GET") is True
    assert should_ignore_request_for_activity("/healthcheck", "GET") is True
    assert should_ignore_request_for_activity("/api/health", "GET") is True
    assert should_ignore_request_for_activity("/api/healthcheck", "GET") is True
    assert should_ignore_request_for_activity("/healthz", "GET") is True
    assert should_ignore_request_for_activity("/ping", "GET") is True

    # Root / uptime checker probes
    assert should_ignore_request_for_activity("/", "GET") is True
    assert should_ignore_request_for_activity("", "GET") is True

    # Documentation and schema routes
    assert should_ignore_request_for_activity("/docs", "GET") is True
    assert should_ignore_request_for_activity("/docs/", "GET") is True
    assert should_ignore_request_for_activity("/redoc", "GET") is True
    assert should_ignore_request_for_activity("/openapi.json", "GET") is True

    # Browser assets
    assert should_ignore_request_for_activity("/favicon.ico", "GET") is True
    assert should_ignore_request_for_activity("/robots.txt", "GET") is True

    # Real human user endpoints MUST NOT be ignored
    assert should_ignore_request_for_activity("/api/positions", "GET") is False
    assert should_ignore_request_for_activity("/api/metrics", "GET") is False
    assert should_ignore_request_for_activity("/api/instruments", "POST") is False
    assert should_ignore_request_for_activity("/api/refresh", "POST") is False
    assert should_ignore_request_for_activity("/api/refresh/stream", "GET") is False


def test_activity_middleware_ignores_healthchecks_and_options_end_to_end():
    """Verify that TestClient requests to /health, /, /docs, and OPTIONS do NOT reset the idle timer."""
    client = TestClient(app)
    auth_headers = {"Authorization": f"Bearer {_mint_test_token()}"}

    # Reset activity tracker to idle (0.0)
    reset_client_activity()
    assert get_last_client_activity() == 0.0

    # 1. Cloud healthcheck: GET /health
    res = client.get("/health")
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "GET /health must NOT count as client activity"

    # 2. Cloud healthcheck alias: GET /healthcheck
    res = client.get("/healthcheck")
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "GET /healthcheck must NOT count as client activity"

    # 3. Root uptime probe: GET /
    res = client.get("/")
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "GET / must NOT count as client activity"

    # 4. API Docs: GET /docs
    res = client.get("/docs")
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "GET /docs must NOT count as client activity"

    # 5. OpenAPI JSON: GET /openapi.json
    res = client.get("/openapi.json")
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "GET /openapi.json must NOT count as client activity"

    # 6. CORS Preflight: OPTIONS /api/positions (with CORS preflight headers)
    res = client.options(
        "/api/positions",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "OPTIONS CORS preflight must NOT count as client activity"

    # 7. Non-CORS OPTIONS request returning 405 also must NOT count as activity
    res = client.options("/api/positions")
    assert res.status_code == 405
    assert get_last_client_activity() == 0.0, "OPTIONS request must NOT count as client activity"

    # 8. HEAD request to /health
    res = client.head("/health")
    assert res.status_code == 200
    assert get_last_client_activity() == 0.0, "HEAD request must NOT count as client activity"

    # 9. Real authenticated user request: GET /api/positions
    res = client.get("/api/positions", headers=auth_headers)
    assert res.status_code == 200
    assert get_last_client_activity() > 0.0, "Real user request to /api/positions MUST record activity"

