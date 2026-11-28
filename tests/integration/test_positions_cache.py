"""Integration tests for in-memory read caching and ETag / 304 Not Modified support."""

from decimal import Decimal
from unittest.mock import MagicMock

from backend.api.dependencies import get_yahoo_provider
from backend.api.main import app
from backend.api.routers.positions import (
    get_cache_stats,
    invalidate_positions_cache,
    reset_cache_stats,
)
from portfoliomaster.core.models import Quote, QuoteStatus


def test_positions_and_metrics_cache_and_etag(sqlite_api_client):
    invalidate_positions_cache()
    reset_cache_stats()

    res1 = sqlite_api_client.get("/api/positions")
    assert res1.status_code == 200
    etag1 = res1.headers.get("ETag")
    assert etag1 is not None
    assert "private" in res1.headers.get("Cache-Control", "")

    stats1 = get_cache_stats()
    misses_initial = stats1["misses"]
    hits_initial = stats1["hits"]
    assert misses_initial >= 1

    res2 = sqlite_api_client.get("/api/positions")
    assert res2.status_code == 200 and res2.headers.get("ETag") == etag1
    stats2 = get_cache_stats()
    assert stats2["hits"] == hits_initial + 1
    assert stats2["misses"] == misses_initial

    res3 = sqlite_api_client.get("/api/positions", headers={"If-None-Match": etag1})
    assert res3.status_code == 304 and res3.text == ""

    invalidate_positions_cache()
    res4 = sqlite_api_client.get("/api/positions")
    assert res4.status_code == 200
    assert get_cache_stats()["misses"] == misses_initial + 1

    # /api/metrics ETag + 304
    reset_cache_stats()
    m1 = sqlite_api_client.get("/api/metrics")
    assert m1.status_code == 200
    m_etag = m1.headers.get("ETag")
    assert m_etag is not None
    m2 = sqlite_api_client.get("/api/metrics", headers={"If-None-Match": m_etag})
    assert m2.status_code == 304 and m2.text == ""


def test_cache_invalidation_after_quote_refresh(sqlite_api_client):
    """Real POST /api/refresh execution invalidates cached /api/positions responses."""
    sqlite_api_client.post(
        "/api/instruments",
        json={"user_ticker": "AAPL", "currency": "USD", "fetch_yahoo": False},
    )
    invalidate_positions_cache()
    reset_cache_stats()

    assert sqlite_api_client.get("/api/positions").status_code == 200
    assert get_cache_stats()["hits"] == 0
    assert get_cache_stats()["misses"] >= 1

    assert sqlite_api_client.get("/api/positions").status_code == 200
    assert get_cache_stats()["hits"] == 1

    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {
        "AAPL": Quote(price=Decimal("205.00"), previous_close=Decimal("200.00"), status=QuoteStatus.FRESH)
    }
    app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter
    res_rf = sqlite_api_client.post("/api/refresh?force=true")
    assert res_rf.status_code == 200

    res3 = sqlite_api_client.get("/api/positions")
    assert res3.status_code == 200
    assert res3.json()["positions"][0]["latest_price"] == 205.0
    assert get_cache_stats()["misses"] >= 2
