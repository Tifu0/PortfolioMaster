"""Integration tests for local SQLite API endpoints and route parity contracts."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.api.dependencies import get_yahoo_provider
from backend.api.main import app
from backend.api.routers import refresh as refresh_router
from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db import session as session_module
from portfoliomaster.db.schema import Base
from tests.conftest import TEST_SECRET, mint_jwt


class TestRootAndPositions:
    def test_root_returns_ok_and_docs(self, sqlite_api_client):
        r = sqlite_api_client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and "docs" in body

    def test_empty_db_returns_empty_list(self, sqlite_api_client):
        r = sqlite_api_client.get("/api/positions")
        assert r.status_code == 200
        assert r.json() == {"positions": [], "count": 0}

    def test_returns_positions_after_insert(self, sqlite_api_client):
        sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "company_name": "Apple Inc.",
            "currency": "USD",
            "fetch_yahoo": False,
            "manual_price": 150.0,
            "manual_previous_close": 148.0,
            "target_price": 200.0,
            "analysis_reference_price": 130.0,
            "start_of_year_price": 125.0,
            "start_of_year_date": "2026-01-02",
        })
        r = sqlite_api_client.get("/api/positions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        pos = body["positions"][0]
        assert pos["user_ticker"] == "AAPL"
        assert pos["latest_price"] == 150.0
        assert pos["previous_close"] == 148.0
        assert pos["start_of_year_price"] == 125.0
        assert pos["start_of_year_date"] == "2026-01-02"
        assert pos["daily_variation_valid"] is True
        assert isinstance(pos["daily_variation"], float)
        assert pos["variation_since_analysis_valid"] is True
        assert pos["decline_to_target_valid"] is True
        assert pos["ytd_variation_valid"] is True and pos["ytd_variation"] == 20.0
        assert "earnings_date" in pos
        assert pos["earnings_date"] is None

    def test_returns_positions_without_quotes_and_metrics(self, sqlite_api_client):
        sqlite_api_client.post("/api/import/confirm", json={
            "instruments": [{
                "user_ticker": "SAN",
                "company_name": "Banco Santander",
                "currency": "EUR",
                "exchange": "SPAIN",
            }]
        })
        pos = sqlite_api_client.get("/api/positions").json()["positions"][0]
        assert pos["user_ticker"] == "SAN"
        assert pos["latest_price"] is None
        assert pos["daily_variation_valid"] is False

        r_met = sqlite_api_client.get("/api/metrics")
        assert r_met.status_code == 200
        assert r_met.json()["total_positions"] == 1
        assert r_met.json()["positions_with_quotes"] == 0
        assert r_met.json()["best_performer"] is None


class TestInstrumentsCRUD:
    def test_list_get_create_update_delete(self, sqlite_api_client):
        assert sqlite_api_client.get("/api/instruments").json()["count"] == 0
        assert sqlite_api_client.get("/api/instruments/NOPE").status_code == 404
        assert sqlite_api_client.put("/api/instruments/NOPE", json={"comment": "x"}).status_code == 404
        assert sqlite_api_client.delete("/api/instruments/NOPE").status_code == 404
        assert sqlite_api_client.post("/api/instruments", json={"user_ticker": "  ", "fetch_yahoo": False}).status_code == 400

        r_bme = sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "BME:SAN",
            "company_name": "Banco Santander",
            "currency": "EUR",
            "fetch_yahoo": False,
        })
        assert r_bme.status_code == 201
        assert r_bme.json()["instrument"]["exchange"] == "SPAIN"
        assert r_bme.json()["instrument"]["provider_symbol"] == "SAN.MC"

        r_manual = sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "AMZN",
            "currency": "USD",
            "fetch_yahoo": False,
            "manual_price": 185.5,
            "manual_previous_close": 183.0,
        })
        assert r_manual.status_code == 201
        assert r_manual.json()["quote"] == {"source": "manual", "price": 185.5}

        today_str = date.today().isoformat()
        r_put = sqlite_api_client.put("/api/instruments/AMZN", json={
            "analysis_date": today_str,
            "analysis_reference_price": 185.5,
            "target_price": 260.0,
            "comment": "Updated thesis",
        })
        assert r_put.status_code == 200
        assert r_put.json()["instrument"]["analysis_date"] == today_str
        assert r_put.json()["instrument"]["target_price"] == 260.0

        r_del = sqlite_api_client.delete("/api/instruments/AMZN")
        assert r_del.status_code == 200 and r_del.json()["deleted"] == "AMZN"
        assert sqlite_api_client.get("/api/instruments/AMZN").status_code == 404

    def test_rename_updates_currency_exchange_and_quote(self, sqlite_api_client):
        sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "OLD_TICKER",
            "company_name": "Old Company SA",
            "currency": "EUR",
            "exchange": "SPAIN",
            "fetch_yahoo": False,
            "manual_price": 50.0,
            "manual_previous_close": 49.0,
        })
        r = sqlite_api_client.put("/api/instruments/OLD_TICKER", json={
            "new_ticker": "NEW_TICKER",
            "company_name": "New Company Inc",
            "currency": "USD",
            "exchange": "US",
            "latest_price": 120.0,
            "previous_close": 118.0,
        })
        assert r.status_code == 200
        assert r.json()["instrument"]["user_ticker"] == "NEW_TICKER"
        assert sqlite_api_client.get("/api/instruments/OLD_TICKER").status_code == 404
        assert sqlite_api_client.get("/api/instruments/NEW_TICKER").status_code == 200

        pos = next(p for p in sqlite_api_client.get("/api/positions").json()["positions"] if p["user_ticker"] == "NEW_TICKER")
        assert pos["latest_price"] == 120.0 and pos["currency"] == "USD"


class TestImportMetricsYtdAndConfig:
    def test_import_flow_and_bad_extension(self, sqlite_api_client, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("Ticker,Empresa,Divisa\nAAPL,Apple,USD\nMSFT,Microsoft,USD\n", encoding="utf-8")
        with open(csv_file, "rb") as f:
            r = sqlite_api_client.post("/api/import/preview", files={"file": ("test.csv", f, "text/csv")})
        assert r.status_code == 200 and r.json()["valid_count"] >= 1

        txt_file = tmp_path / "bad.txt"
        txt_file.write_text("hello")
        with open(txt_file, "rb") as f:
            assert sqlite_api_client.post("/api/import/preview", files={"file": ("bad.txt", f, "text/plain")}).status_code == 400

        r_confirm = sqlite_api_client.post("/api/import/confirm", json={
            "instruments": [{
                "user_ticker": "NVDA",
                "provider_symbol": "NVDA",
                "exchange": "US",
                "currency": "USD",
                "company_name": "NVIDIA",
                "comment": "",
                "active": True,
            }]
        })
        assert r_confirm.status_code == 200 and r_confirm.json()["committed"] == 1
        assert sqlite_api_client.get("/api/instruments/NVDA").status_code == 200

    def test_metrics_and_database_wipe(self, sqlite_api_client):
        assert sqlite_api_client.get("/api/metrics").json()["total_positions"] == 0
        sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "AAPL", "currency": "USD", "fetch_yahoo": False, "manual_price": 150.0, "manual_previous_close": 100.0
        })
        sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "MSFT", "currency": "USD", "fetch_yahoo": False, "manual_price": 90.0, "manual_previous_close": 100.0
        })
        body = sqlite_api_client.get("/api/metrics").json()
        assert body["total_positions"] == 2 and body["positions_with_quotes"] == 2
        assert body["best_performer"]["user_ticker"] == "AAPL" and body["best_performer"]["daily_variation"] == 50.0
        assert body["worst_performer"]["user_ticker"] == "MSFT" and body["worst_performer"]["daily_variation"] == -10.0
        assert body["average_daily_change"] == 20.0

        assert sqlite_api_client.delete("/api/database").status_code == 200
        assert sqlite_api_client.get("/api/instruments").json()["count"] == 0

    def test_ytd_endpoints_and_single_refresh_resolution(self, sqlite_api_client, monkeypatch):
        assert sqlite_api_client.post("/api/instruments/NONEXISTENT/fetch-ytd-price").status_code == 404
        r_batch = sqlite_api_client.post("/api/instruments/resolve-missing-ytd-prices")
        assert r_batch.status_code == 200 and {"status", "updated", "failed", "skipped", "total"} <= set(r_batch.json().keys())

        mock_quote = Quote(price=Decimal("155.0"), previous_close=Decimal("150.0"), status=QuoteStatus.FRESH, provider="Yahoo")
        mock_adapter = MagicMock()
        mock_adapter.fetch.side_effect = lambda symbols: {symbols[0]: mock_quote}
        app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter
        monkeypatch.setattr(refresh_router, "_get_historical_quote_for_date", lambda s, dt: 140.0)
        monkeypatch.setattr(refresh_router, "_get_start_of_year_quote", lambda s, yr: (130.0, date(yr, 1, 2)))

        sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "MSFT_TEST", "currency": "USD", "fetch_yahoo": False, "analysis_date": date.today().isoformat()
        })
        r = sqlite_api_client.post("/api/instruments/MSFT_TEST/refresh")
        assert r.status_code == 200
        assert r.json()["price"] == 155.0 and r.json()["analysis_reference_price"] == 140.0
        pos = next(p for p in sqlite_api_client.get("/api/positions").json()["positions"] if p["user_ticker"] == "MSFT_TEST")
        assert pos["analysis_reference_price"] == 140.0 and pos["variation_since_analysis_valid"] is True

    def test_config_health_aliases_and_stream(self, sqlite_api_client):
        for path in ("/health", "/healthcheck", "/api/health", "/api/healthcheck"):
            r = sqlite_api_client.get(path)
            assert r.status_code == 200 and r.json() == {"status": "ok", "database": "connected"}

        cfg = sqlite_api_client.get("/api/config").json()
        assert cfg["status"] == "ok" and cfg["batch_size"] >= 1
        assert {"refresh_interval_seconds", "is_refreshing", "refresh_counter", "current_batch", "total_batches", "processed_symbols", "total_symbols"} <= set(cfg.keys())

        mock_adapter = MagicMock()
        mock_adapter.fetch.return_value = {}
        app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter
        c_before = cfg["refresh_counter"]
        refresh_router._execute_refresh_all()
        cfg_after = sqlite_api_client.get("/api/config").json()
        assert cfg_after["refresh_counter"] > c_before and cfg_after["last_refresh_at"] is not None

        def _trigger():
            time.sleep(0.05)
            sqlite_api_client.post("/api/refresh?background=true")

        threading.Thread(target=_trigger, daemon=True).start()
        with sqlite_api_client.stream("GET", "/api/refresh/stream") as response:
            assert response.status_code == 200 and "text/event-stream" in response.headers.get("content-type", "")
            lines = [line for line in response.iter_lines() if line and line.startswith("data:")]
            assert any("connected" in line for line in lines)


class TestCurrencyAndActiveOnlyParity:
    def test_create_with_currency_auto_is_normalized(self, isolated_mt_env):
        client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
        r1 = client.post("/api/instruments", json={"user_ticker": "SAN_TEST", "currency": "AUTO", "exchange": "SPAIN", "fetch_yahoo": False})
        assert r1.status_code == 201 and r1.json()["instrument"]["currency"] == "EUR"
        assert client.get("/api/instruments/SAN_TEST").json()["instrument"]["currency"] == "EUR"

        r2 = client.post("/api/instruments", json={"user_ticker": "AAPL_TEST", "currency": "", "exchange": "US", "fetch_yahoo": False})
        assert r2.status_code == 201 and r2.json()["instrument"]["currency"] == "USD"

    def test_active_only_parity_across_modes(self, sqlite_api_client, monkeypatch, tmp_path):
        # 1. SQLite mode
        sqlite_api_client.post("/api/instruments", json={"user_ticker": "ACT_SQL", "currency": "USD", "fetch_yahoo": False})
        sqlite_api_client.post("/api/instruments", json={"user_ticker": "INACT_SQL", "currency": "USD", "fetch_yahoo": False})
        sqlite_api_client.put("/api/instruments/INACT_SQL", json={"active": False})

        assert [p["user_ticker"] for p in sqlite_api_client.get("/api/positions?active_only=true").json()["positions"]] == ["ACT_SQL"]
        assert set(p["user_ticker"] for p in sqlite_api_client.get("/api/positions?active_only=false").json()["positions"]) == {"ACT_SQL", "INACT_SQL"}
        assert set(p["user_ticker"] for p in sqlite_api_client.get("/api/positions").json()["positions"]) == {"ACT_SQL", "INACT_SQL"}

        # 2. Multi-tenant Postgres mode
        test_db = tmp_path / "active_mt.db"
        monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")
        session_module._ENGINE = None
        session_module._SESSION_FACTORY = None
        Base.metadata.create_all(session_module.get_engine(f"sqlite:///{test_db}"))

        mt_client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4())}"})
        mt_client.post("/api/instruments", json={"user_ticker": "ACT_CO", "currency": "USD", "fetch_yahoo": False})
        mt_client.post("/api/instruments", json={"user_ticker": "INACT_CO", "currency": "USD", "fetch_yahoo": False})
        mt_client.put("/api/instruments/INACT_CO", json={"active": False})

        assert [p["user_ticker"] for p in mt_client.get("/api/positions?active_only=true").json()["positions"]] == ["ACT_CO"]
        assert set(p["user_ticker"] for p in mt_client.get("/api/positions?active_only=false").json()["positions"]) == {"ACT_CO", "INACT_CO"}
        assert set(p["user_ticker"] for p in mt_client.get("/api/positions").json()["positions"]) == {"ACT_CO", "INACT_CO"}
