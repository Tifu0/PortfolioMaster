"""Tests for concrete route fixes:
1. Currency normalization: 'AUTO', '', and None are never persisted as 'AUTO'.
2. Active_only semantics parity across SQLite and multi-tenant PostgreSQL.
"""

from __future__ import annotations

import time
import uuid
import jwt
from fastapi.testclient import TestClient

from backend.api.main import app
from portfoliomaster.db.schema import Base
import portfoliomaster.db.session as session_module

TEST_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"


def mint_token(user_id: uuid.UUID) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


class TestCurrencyNormalization:
    """Test that currency is always normalized and 'AUTO' is never persisted."""

    def test_create_with_currency_auto_is_normalized(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
        test_db = tmp_path / "test_curr_auto.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")

        session_module._ENGINE = None
        session_module._SESSION_FACTORY = None
        eng = session_module.get_engine(f"sqlite:///{test_db}")
        Base.metadata.create_all(eng)

        user_id = uuid.uuid4()
        client = TestClient(app, headers={"Authorization": f"Bearer {mint_token(user_id)}"})

        # 1. Currency explicitly passed as "AUTO"
        r1 = client.post("/api/instruments", json={
            "user_ticker": "SAN_TEST",
            "currency": "AUTO",
            "exchange": "SPAIN",
            "fetch_yahoo": False,
        })
        assert r1.status_code == 201
        inst1 = r1.json()["instrument"]
        assert inst1["currency"] != "AUTO"
        assert inst1["currency"] == "EUR"

        # Check DB query
        r_get1 = client.get("/api/instruments/SAN_TEST")
        assert r_get1.status_code == 200
        assert r_get1.json()["currency"] != "AUTO"
        assert r_get1.json()["currency"] == "EUR"

        # 2. Currency empty string
        r2 = client.post("/api/instruments", json={
            "user_ticker": "AAPL_TEST",
            "currency": "",
            "exchange": "US",
            "fetch_yahoo": False,
        })
        assert r2.status_code == 201
        inst2 = r2.json()["instrument"]
        assert inst2["currency"] == "USD"

        # 3. Currency explicit EUR
        r3 = client.post("/api/instruments", json={
            "user_ticker": "BME_TEST",
            "currency": "EUR",
            "exchange": "SPAIN",
            "fetch_yahoo": False,
        })
        assert r3.status_code == 201
        assert r3.json()["instrument"]["currency"] == "EUR"

        session_module._ENGINE = None
        session_module._SESSION_FACTORY = None


class TestActiveOnlySemanticsParity:
    """Test active_only query parameter contract parity:
    - active_only=True: returns only active
    - active_only=False: returns all instruments (both active and inactive)
    - active_only omitted (None): returns all instruments
    """

    def test_active_only_in_multi_tenant_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
        test_db = tmp_path / "test_active_mt.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")

        session_module._ENGINE = None
        session_module._SESSION_FACTORY = None
        eng = session_module.get_engine(f"sqlite:///{test_db}")
        Base.metadata.create_all(eng)

        user_id = uuid.uuid4()
        client = TestClient(app, headers={"Authorization": f"Bearer {mint_token(user_id)}"})

        # Create active instrument
        client.post("/api/instruments", json={
            "user_ticker": "ACT_CO",
            "currency": "USD",
            "fetch_yahoo": False,
        })

        # Create inactive instrument
        client.post("/api/instruments", json={
            "user_ticker": "INACT_CO",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        client.put("/api/instruments/INACT_CO", json={"active": False})

        # Test active_only=true
        res_true = client.get("/api/positions?active_only=true").json()
        tickers_true = [p["user_ticker"] for p in res_true["positions"]]
        assert "ACT_CO" in tickers_true
        assert "INACT_CO" not in tickers_true

        # Test active_only=false (returns all)
        res_false = client.get("/api/positions?active_only=false").json()
        tickers_false = [p["user_ticker"] for p in res_false["positions"]]
        assert "ACT_CO" in tickers_false
        assert "INACT_CO" in tickers_false

        # Test active_only omitted (returns all)
        res_none = client.get("/api/positions").json()
        tickers_none = [p["user_ticker"] for p in res_none["positions"]]
        assert "ACT_CO" in tickers_none
        assert "INACT_CO" in tickers_none

        session_module._ENGINE = None
        session_module._SESSION_FACTORY = None

    def test_active_only_in_sqlite_mode(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
        monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
        test_db = tmp_path / "test_active_sqlite.db"
        monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", str(test_db))
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")

        from portfoliomaster.db.connection import init_db
        init_db()

        user_id = uuid.uuid4()
        client = TestClient(app, headers={"Authorization": f"Bearer {mint_token(user_id)}"})

        # Create active instrument
        client.post("/api/instruments", json={
            "user_ticker": "ACT_SQL",
            "currency": "USD",
            "fetch_yahoo": False,
        })

        # Create inactive instrument
        client.post("/api/instruments", json={
            "user_ticker": "INACT_SQL",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        client.put("/api/instruments/INACT_SQL", json={"active": False})

        # Test active_only=true
        res_true = client.get("/api/positions?active_only=true").json()
        tickers_true = [p["user_ticker"] for p in res_true["positions"]]
        assert "ACT_SQL" in tickers_true
        assert "INACT_SQL" not in tickers_true

        # Test active_only=false (returns all)
        res_false = client.get("/api/positions?active_only=false").json()
        tickers_false = [p["user_ticker"] for p in res_false["positions"]]
        assert "ACT_SQL" in tickers_false
        assert "INACT_SQL" in tickers_false

        # Test active_only omitted (returns all)
        res_none = client.get("/api/positions").json()
        tickers_none = [p["user_ticker"] for p in res_none["positions"]]
        assert "ACT_SQL" in tickers_none
        assert "INACT_SQL" in tickers_none
