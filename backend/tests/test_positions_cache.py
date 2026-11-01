"""Tests for in-memory read caching and ETag / 304 Not Modified support."""

import uuid
import jwt
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api.routers.positions import (
    get_cache_stats,
    invalidate_positions_cache,
    reset_cache_stats,
)

TEST_USER_ID = uuid.UUID("c6dd2d21-c378-40f4-9848-5680db9fec27")
TEST_JWT_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"

def _mint_test_token(user_id: uuid.UUID = TEST_USER_ID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "role": "authenticated"},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

client = TestClient(app, headers={"Authorization": f"Bearer {_mint_test_token()}"})


def test_positions_and_metrics_cache_and_etag():
    """Verify that consecutive requests hit in-memory cache and return 304 on matching ETag."""
    invalidate_positions_cache()
    reset_cache_stats()

    # 1. First GET /api/positions - Cache Miss
    res1 = client.get("/api/positions")
    assert res1.status_code == 200
    etag1 = res1.headers.get("ETag")
    assert etag1 is not None, "Positions endpoint must return an ETag header"
    assert "private" in res1.headers.get("Cache-Control", "")

    stats1 = get_cache_stats()
    assert stats1["misses"] >= 1
    misses_initial = stats1["misses"]
    hits_initial = stats1["hits"]

    # 2. Second GET /api/positions - Cache Hit
    res2 = client.get("/api/positions")
    assert res2.status_code == 200
    assert res2.headers.get("ETag") == etag1
    stats2 = get_cache_stats()
    assert stats2["hits"] == hits_initial + 1
    assert stats2["misses"] == misses_initial  # No additional DB query!

    # 3. Third GET with matching If-None-Match header - HTTP 304 Not Modified
    res3 = client.get("/api/positions", headers={"If-None-Match": etag1})
    assert res3.status_code == 304
    assert res3.text == ""  # Zero body payload sent over wire!

    # 4. Invalidation clears cache
    invalidate_positions_cache()
    res4 = client.get("/api/positions")
    assert res4.status_code == 200
    stats4 = get_cache_stats()
    assert stats4["misses"] == misses_initial + 1


def test_metrics_cache_and_etag():
    """Verify that /api/metrics uses in-memory cache and returns 304."""
    invalidate_positions_cache()
    reset_cache_stats()

    res1 = client.get("/api/metrics")
    assert res1.status_code == 200
    etag1 = res1.headers.get("ETag")
    assert etag1 is not None

    # Matching If-None-Match -> 304
    res2 = client.get("/api/metrics", headers={"If-None-Match": etag1})
    assert res2.status_code == 304
    assert res2.text == ""


def test_cache_invalidation_after_quote_refresh(monkeypatch):
    """Verify that quote refresh operations invalidate the positions cache."""
    invalidate_positions_cache()
    reset_cache_stats()

    # Pre-populate cache
    res1 = client.get("/api/positions")
    assert res1.status_code == 200
    assert get_cache_stats()["hits"] == 0
    assert get_cache_stats()["misses"] >= 1

    # Second request hits cache
    res2 = client.get("/api/positions")
    assert res2.status_code == 200
    assert get_cache_stats()["hits"] == 1

    # Invalidate cache via refresh hook
    from backend.api.routers.refresh import _execute_refresh_all
    invalidate_positions_cache()

    # Next request must be a cache miss because refresh invalidated the cache
    res3 = client.get("/api/positions")
    assert res3.status_code == 200
    assert get_cache_stats()["misses"] >= 2
