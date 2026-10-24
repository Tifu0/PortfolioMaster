"""Tests for Server Refresh Cooldown and Safe Market Data Fetching.

Verifies:
1. First /api/refresh call queries the market provider and updates quotes.
2. Second /api/refresh call within 5 seconds triggers cooldown:
   skips the market provider and returns refreshed_count == 0 with status == "fresh".
3. Single instrument /api/instruments/{ticker}/refresh respects cooldown.
4. force=True flag bypasses cooldown when explicitly requested.
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from unittest.mock import MagicMock

# Force an isolated temporary SQLite database for unit testing
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["PORTFOLIOMASTER_DB_PATH"] = _tmp_db.name
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import pytest
from fastapi.testclient import TestClient

import uuid
import jwt
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db.connection import init_db
from portfoliomaster.db.repository import upsert_instrument, wipe_database
from backend.api.main import app

TEST_USER_ID = uuid.UUID("c6dd2d21-c378-40f4-9848-5680db9fec27")
TEST_JWT_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET

def _mint_test_token(user_id: uuid.UUID = TEST_USER_ID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "role": "authenticated"},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

init_db()
client = TestClient(app, headers={"Authorization": f"Bearer {_mint_test_token()}"})


@pytest.fixture(autouse=True)
def _setup_clean_environment(monkeypatch):
    """Ensure clean database and isolated test environment."""
    wipe_database()
    yield
    wipe_database()


def test_consecutive_refresh_calls_trigger_cooldown(monkeypatch):
    """
    Test requirement:
    Simulate two consecutive calls to /api/refresh with 5 seconds difference:
    - 1st call invokes mock provider and registers update.
    - 2nd call skips provider and returns refreshed_count == 0 with status: 'fresh'.
    """
    # 1. Insert an active instrument
    inst = Instrument(
        user_ticker="SAN.MC",
        provider_symbol="SAN.MC",
        exchange=Exchange.SPAIN,
        currency="EUR",
        company_name="Banco Santander",
        active=True,
    )
    upsert_instrument(inst)

    # 2. Setup mock provider
    mock_quote = Quote(
        price=Decimal("4.50"),
        previous_close=Decimal("4.40"),
        status=QuoteStatus.FRESH,
        provider="yahoo_mock",
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"SAN.MC": mock_quote}

    # Patch provider resolver
    monkeypatch.setattr("backend.api.routers.refresh._get_yahoo_adapter", lambda: mock_adapter)

    # 3. First call to /api/refresh: Must invoke provider and refresh
    res1 = client.post("/api/refresh")
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["status"] == "ok"
    assert body1["refreshed_count"] >= 1
    assert body1["updated"] >= 1
    assert mock_adapter.fetch.call_count == 1

    # 4. Second call to /api/refresh immediately (simulating 5s later, well within 120s cooldown)
    res2 = client.post("/api/refresh")
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["status"] == "fresh"
    assert body2["refreshed_count"] == 0
    assert "Precios actualizados recientemente" in body2.get("message", "")
    # The provider MUST NOT have been called a second time
    assert mock_adapter.fetch.call_count == 1


def test_single_instrument_cooldown(monkeypatch):
    """
    Verify /api/instruments/{ticker}/refresh obeys 30s cooldown and force bypass.
    """
    inst = Instrument(
        user_ticker="IBE.MC",
        provider_symbol="IBE.MC",
        exchange=Exchange.SPAIN,
        currency="EUR",
        company_name="Iberdrola",
        active=True,
    )
    upsert_instrument(inst)

    mock_quote = Quote(
        price=Decimal("12.20"),
        previous_close=Decimal("12.00"),
        status=QuoteStatus.FRESH,
        provider="yahoo_mock",
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"IBE.MC": mock_quote}
    monkeypatch.setattr("backend.api.routers.refresh._get_yahoo_adapter", lambda: mock_adapter)

    # 1st call: Refreshes instrument
    r1 = client.post("/api/instruments/IBE.MC/refresh")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"
    assert r1.json()["price"] == 12.20
    assert mock_adapter.fetch.call_count == 1

    # 2nd call: Cooldown active
    r2 = client.post("/api/instruments/IBE.MC/refresh")
    assert r2.status_code == 200
    assert r2.json()["status"] == "fresh"
    assert r2.json()["refreshed_count"] == 0
    assert mock_adapter.fetch.call_count == 1

    # 3rd call with force=true: Bypasses cooldown
    r3 = client.post("/api/instruments/IBE.MC/refresh?force=true")
    assert r3.status_code == 200
    assert r3.json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 2


def test_refresh_all_force_bypasses_cooldown(monkeypatch):
    """Verify force=True flag on /api/refresh bypasses stale threshold."""
    inst = Instrument(
        user_ticker="TEF.MC",
        provider_symbol="TEF.MC",
        exchange=Exchange.SPAIN,
        currency="EUR",
        company_name="Telefonica",
        active=True,
    )
    upsert_instrument(inst)

    mock_quote = Quote(
        price=Decimal("3.80"),
        previous_close=Decimal("3.75"),
        status=QuoteStatus.FRESH,
        provider="yahoo_mock",
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"TEF.MC": mock_quote}
    monkeypatch.setattr("backend.api.routers.refresh._get_yahoo_adapter", lambda: mock_adapter)

    # 1st call
    r1 = client.post("/api/refresh")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 1

    # 2nd call with force=true
    r2 = client.post("/api/refresh?force=true")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 2
