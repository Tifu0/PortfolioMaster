"""Phase 1 integration tests — verify every endpoint returns the expected shape.

Run from the project root:
    pytest backend/tests/test_api.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the src package is importable even when running pytest from
# various working directories.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Use an isolated in-memory (or temp-file) database so tests never touch
# the real portfolio.db.
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["PORTFOLIOMASTER_DB_PATH"] = _tmp_db.name

from fastapi.testclient import TestClient
from portfoliomaster.db.connection import init_db

# Initialize tables in temporary database
init_db()

# pyrefly: ignore [missing-import]
from backend.api.main import app  # noqa: E402

client = TestClient(app)


# ---------------------------------------------------------------------- #
# Fixtures
# ---------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clean_db():
    """Wipe the DB before each test so tests are independent."""
    client.delete("/api/database")
    yield
    # nothing to tear down — next test wipes again


# ---------------------------------------------------------------------- #
# GET / (Root healthcheck & docs link)
# ---------------------------------------------------------------------- #

class TestRoot:
    def test_root_returns_ok_and_docs(self):
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "docs" in body


# ---------------------------------------------------------------------- #
# GET /api/positions
# ---------------------------------------------------------------------- #

class TestGetPositions:
    def test_empty_db_returns_empty_list(self):
        r = client.get("/api/positions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0
        assert body["positions"] == []

    def test_returns_positions_after_insert(self):
        # create an instrument with a manual price
        client.post("/api/instruments", json={
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

        r = client.get("/api/positions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1

        pos = body["positions"][0]
        assert pos["user_ticker"] == "AAPL"
        assert pos["latest_price"] == 150.0
        assert pos["previous_close"] == 148.0
        assert pos["start_of_year_price"] == 125.0
        assert pos["start_of_year_date"] == "2026-01-02"

        # Computed columns must be present and valid
        assert pos["daily_variation_valid"] is True
        assert isinstance(pos["daily_variation"], float)
        assert pos["variation_since_analysis_valid"] is True
        assert pos["decline_to_target_valid"] is True
        assert pos["ytd_variation_valid"] is True
        assert pos["ytd_variation"] == 20.0

    def test_returns_positions_without_quotes(self):
        # Insert instrument without quotes (e.g. from import)
        client.post("/api/import/confirm", json={
            "instruments": [
                {
                    "user_ticker": "SAN",
                    "company_name": "Banco Santander",
                    "currency": "EUR",
                    "exchange": "SPAIN",
                }
            ]
        })

        r = client.get("/api/positions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        pos = body["positions"][0]
        assert pos["user_ticker"] == "SAN"
        assert pos["latest_price"] is None
        assert pos["quote_status"] is None
        assert pos["daily_variation"] is None
        assert pos["daily_variation_valid"] is False

        # Verify metrics doesn't crash on unquoted positions
        r_met = client.get("/api/metrics")
        assert r_met.status_code == 200
        assert r_met.json()["total_positions"] == 1
        assert r_met.json()["positions_with_quotes"] == 0
        assert r_met.json()["best_performer"] is None


# ---------------------------------------------------------------------- #
# GET /api/instruments
# ---------------------------------------------------------------------- #

class TestListInstruments:
    def test_empty(self):
        r = client.get("/api/instruments")
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_after_insert(self):
        client.post("/api/instruments", json={
            "user_ticker": "MSFT",
            "company_name": "Microsoft",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        r = client.get("/api/instruments")
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["instruments"][0]["user_ticker"] == "MSFT"


# ---------------------------------------------------------------------- #
# GET /api/instruments/{ticker}
# ---------------------------------------------------------------------- #

class TestGetInstrument:
    def test_not_found(self):
        r = client.get("/api/instruments/NOPE")
        assert r.status_code == 404

    def test_found(self):
        client.post("/api/instruments", json={
            "user_ticker": "GOOG",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        r = client.get("/api/instruments/GOOG")
        assert r.status_code == 200
        assert r.json()["user_ticker"] == "GOOG"


# ---------------------------------------------------------------------- #
# POST /api/instruments
# ---------------------------------------------------------------------- #

class TestCreateInstrument:
    def test_create_minimal(self):
        r = client.post("/api/instruments", json={
            "user_ticker": "TSLA",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        assert r.status_code == 201
        assert r.json()["status"] == "ok"
        assert r.json()["instrument"]["user_ticker"] == "TSLA"

    def test_create_with_manual_price(self):
        r = client.post("/api/instruments", json={
            "user_ticker": "AMZN",
            "currency": "USD",
            "fetch_yahoo": False,
            "manual_price": 185.5,
            "manual_previous_close": 183.0,
        })
        assert r.status_code == 201
        assert r.json()["quote"]["source"] == "manual"
        assert r.json()["quote"]["price"] == 185.5

    def test_create_with_exchange_prefix(self):
        r = client.post("/api/instruments", json={
            "user_ticker": "BME:SAN",
            "company_name": "Banco Santander",
            "currency": "EUR",
            "fetch_yahoo": False,
        })
        assert r.status_code == 201
        inst = r.json()["instrument"]
        assert inst["exchange"] == "SPAIN"
        assert inst["provider_symbol"] == "SAN.MC"

    def test_create_missing_ticker(self):
        r = client.post("/api/instruments", json={
            "user_ticker": "  ",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------- #
# PUT /api/instruments/{ticker}
# ---------------------------------------------------------------------- #

class TestUpdateInstrument:
    def test_update_fields(self):
        client.post("/api/instruments", json={
            "user_ticker": "META",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        r = client.put("/api/instruments/META", json={
            "company_name": "Meta Platforms Inc.",
            "target_price": 600.0,
            "comment": "Strong earnings",
        })
        assert r.status_code == 200
        inst = r.json()["instrument"]
        assert inst["company_name"] == "Meta Platforms Inc."
        assert inst["target_price"] == 600.0

    def test_update_save_and_update_analysis_date_single_put(self):
        """Verify single-request save and update analysis date + synced reference price."""
        from datetime import date
        today_str = date.today().isoformat()

        # Create test instrument with older analysis date
        client.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "currency": "USD",
            "fetch_yahoo": False,
            "manual_price": 225.50,
        })

        # Send single PUT overriding analysis_date to today and analysis_reference_price to quote price
        r = client.put("/api/instruments/AAPL", json={
            "analysis_date": today_str,
            "analysis_reference_price": 225.50,
            "target_price": 260.00,
            "comment": "Updated thesis",
        })
        assert r.status_code == 200
        inst = r.json()["instrument"]
        assert inst["analysis_date"] == today_str
        assert inst["analysis_reference_price"] == 225.50
        assert inst["target_price"] == 260.00
        assert inst["comment"] == "Updated thesis"

    def test_update_rename_ticker(self):
        client.post("/api/instruments", json={
            "user_ticker": "AMZN_OLD",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        r = client.put("/api/instruments/AMZN_OLD", json={
            "new_ticker": "AMZN_NEW",
            "company_name": "Amazon New",
        })
        assert r.status_code == 200
        inst = r.json()["instrument"]
        assert inst["user_ticker"] == "AMZN_NEW"
        assert inst["company_name"] == "Amazon New"

        # Verify old ticker returns 404, new returns 200
        assert client.get("/api/instruments/AMZN_OLD").status_code == 404
        assert client.get("/api/instruments/AMZN_NEW").status_code == 200

    def test_update_not_found(self):
        r = client.put("/api/instruments/NOPE", json={"comment": "x"})
        assert r.status_code == 404


# ---------------------------------------------------------------------- #
# GET /api/instruments/check-yahoo
# ---------------------------------------------------------------------- #

class TestCheckYahooTicker:
    def test_check_empty_ticker(self):
        r = client.get("/api/instruments/check-yahoo?ticker=")
        assert r.status_code == 400

    def test_check_valid_ticker_shape(self):
        r = client.get("/api/instruments/check-yahoo?ticker=AAPL")
        assert r.status_code == 200
        data = r.json()
        assert "available" in data
        assert "status" in data
        assert data["ticker"] == "AAPL"


# ---------------------------------------------------------------------- #
# DELETE /api/instruments/{ticker}
# ---------------------------------------------------------------------- #

class TestDeleteInstrument:
    def test_delete_existing(self):
        client.post("/api/instruments", json={
            "user_ticker": "NFLX",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        r = client.delete("/api/instruments/NFLX")
        assert r.status_code == 200
        assert r.json()["deleted"] == "NFLX"

        # confirm it's gone
        r2 = client.get("/api/instruments/NFLX")
        assert r2.status_code == 404

    def test_delete_not_found(self):
        r = client.delete("/api/instruments/NOPE")
        assert r.status_code == 404


# ---------------------------------------------------------------------- #
# POST /api/import/preview  +  POST /api/import/confirm
# ---------------------------------------------------------------------- #

class TestImportFlow:
    def test_preview_csv(self, tmp_path):
        csv_content = "Ticker,Empresa,Divisa\nAAPL,Apple,USD\nMSFT,Microsoft,USD\n"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with open(csv_file, "rb") as f:
            r = client.post(
                "/api/import/preview",
                files={"file": ("test.csv", f, "text/csv")},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["valid_count"] >= 1
        assert isinstance(body["instruments"], list)
        assert isinstance(body["errors"], list)
        assert isinstance(body["warnings"], list)

    def test_confirm_import(self):
        r = client.post("/api/import/confirm", json={
            "instruments": [
                {
                    "user_ticker": "NVDA",
                    "provider_symbol": "NVDA",
                    "exchange": "US",
                    "currency": "USD",
                    "company_name": "NVIDIA",
                    "comment": "",
                    "active": True,
                }
            ]
        })
        assert r.status_code == 200
        assert r.json()["committed"] == 1

        # Verify it's in the DB
        r2 = client.get("/api/instruments/NVDA")
        assert r2.status_code == 200

    def test_preview_bad_extension(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        with open(txt_file, "rb") as f:
            r = client.post(
                "/api/import/preview",
                files={"file": ("test.txt", f, "text/plain")},
            )
        assert r.status_code == 400


# ---------------------------------------------------------------------- #
# GET /api/metrics
# ---------------------------------------------------------------------- #

class TestGetMetrics:
    def test_empty_metrics(self):
        client.delete("/api/database")
        r = client.get("/api/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["total_positions"] == 0
        assert body["positions_with_quotes"] == 0
        assert body["best_performer"] is None
        assert body["worst_performer"] is None
        assert body["average_daily_change"] is None
        assert body["positive_count"] == 0
        assert body["negative_count"] == 0
        assert body["neutral_count"] == 0

    def test_metrics_with_positions(self):
        client.delete("/api/database")
        # Gainer (+50%)
        client.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "company_name": "Apple Inc.",
            "currency": "USD",
            "fetch_yahoo": False,
            "manual_price": 150.0,
            "manual_previous_close": 100.0,
        })
        # Loser (-10%)
        client.post("/api/instruments", json={
            "user_ticker": "MSFT",
            "company_name": "Microsoft Corp.",
            "currency": "USD",
            "fetch_yahoo": False,
            "manual_price": 90.0,
            "manual_previous_close": 100.0,
        })
        r = client.get("/api/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["total_positions"] == 2
        assert body["positions_with_quotes"] == 2
        assert body["best_performer"]["user_ticker"] == "AAPL"
        assert body["best_performer"]["daily_variation"] == 50.0
        assert body["worst_performer"]["user_ticker"] == "MSFT"
        assert body["worst_performer"]["daily_variation"] == -10.0
        assert body["positive_count"] == 1
        assert body["negative_count"] == 1
        assert body["average_daily_change"] == 20.0


# ---------------------------------------------------------------------- #
# DELETE /api/database
# ---------------------------------------------------------------------- #

class TestWipeDatabase:
    def test_wipe(self):
        client.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        r = client.delete("/api/database")
        assert r.status_code == 200

        r2 = client.get("/api/instruments")
        assert r2.json()["count"] == 0


# ---------------------------------------------------------------------- #
# POST /api/instruments/{ticker}/fetch-ytd-price & resolve-missing-ytd-prices
# ---------------------------------------------------------------------- #

class TestYtdEndpoints:
    def test_fetch_ytd_price_not_found(self):
        r = client.post("/api/instruments/NONEXISTENT/fetch-ytd-price")
        assert r.status_code == 404

    def test_resolve_missing_ytd_prices(self):
        r = client.post("/api/instruments/resolve-missing-ytd-prices")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "updated" in body
        assert "failed" in body
        assert "skipped" in body
        assert "total" in body


# ---------------------------------------------------------------------- #
# GET /api/config
# ---------------------------------------------------------------------- #

class TestConfig:
    def test_get_config_returns_expected_fields(self):
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "refresh_interval_seconds" in body
        assert "batch_size" in body
        assert isinstance(body["refresh_interval_seconds"], (int, float))
        assert isinstance(body["batch_size"], int)
        assert body["batch_size"] >= 1
        assert "is_refreshing" in body
        assert isinstance(body["is_refreshing"], bool)
        assert "refresh_counter" in body
        assert isinstance(body["refresh_counter"], int)

    def test_execute_refresh_all_increments_refresh_counter(self, monkeypatch):
        from backend.api.main import _execute_refresh_all
        from unittest.mock import MagicMock

        # Mock YahooAdapter to avoid network call
        mock_adapter = MagicMock()
        mock_adapter.fetch.return_value = {}
        monkeypatch.setattr("backend.api.main.YahooAdapter", lambda: mock_adapter)

        r_before = client.get("/api/config").json()
        c_before = r_before.get("refresh_counter", 0)

        _execute_refresh_all()

        r_after = client.get("/api/config").json()
        c_after = r_after.get("refresh_counter", 0)
        assert c_after > c_before
        assert r_after["last_refresh_at"] is not None
        assert r_after["is_refreshing"] is False

    def test_get_config_includes_batch_progress_fields(self):
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert "current_batch" in body
        assert "total_batches" in body
        assert "processed_symbols" in body
        assert "total_symbols" in body

    def test_refresh_stream_endpoint(self, monkeypatch):
        from unittest.mock import MagicMock
        mock_adapter = MagicMock()
        mock_adapter.fetch.return_value = {}
        monkeypatch.setattr("backend.api.main.YahooAdapter", lambda: mock_adapter)

        with client.stream("GET", "/api/refresh/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 2:
                    break
            assert any("start" in l or "complete" in l for l in lines)




# ---------------------------------------------------------------------- #
# Historical Price Resolution & Fallback Tests (Issue 4 & Issue 1)
# ---------------------------------------------------------------------- #

class TestHistoricalPriceResolution:
    def test_fetch_historical_quote_fallback_to_fast_info(self, monkeypatch):
        from unittest.mock import MagicMock
        from datetime import date
        from backend.api.main import _fetch_historical_quote_and_date
        import pandas as pd

        # Mock yf.Ticker to simulate empty history() (e.g. today intraday or closed market)
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_fast_info = MagicMock()
        mock_fast_info.last_price = 215.75
        mock_fast_info.previous_close = 214.50
        mock_ticker.fast_info = mock_fast_info

        monkeypatch.setattr("yfinance.Ticker", lambda symbol: mock_ticker)

        today = date.today()
        result = _fetch_historical_quote_and_date("AAPL", today)
        assert result is not None
        price, dt = result
        assert price == 215.75
        assert dt == today

    def test_fetch_historical_quote_lookback_to_previous_trading_day(self, monkeypatch):
        from unittest.mock import MagicMock
        from datetime import date
        from backend.api.main import _fetch_historical_quote_and_date
        import pandas as pd

        # Simulate target date is Sunday 2026-10-18, and history returns Friday 2026-10-16
        friday_dt = pd.Timestamp("2026-10-16")
        hist_df = pd.DataFrame({"Close": [198.25]}, index=[friday_dt])

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = hist_df

        monkeypatch.setattr("yfinance.Ticker", lambda symbol: mock_ticker)

        sunday = date(2026, 10, 18)
        result = _fetch_historical_quote_and_date("AAPL", sunday)
        assert result is not None
        price, dt = result
        assert price == 198.25
        assert dt == date(2026, 10, 16)


# ---------------------------------------------------------------------- #
# Single Row Refresh Auto-Resolution Tests (Issue 1)
# ---------------------------------------------------------------------- #

class TestRefreshSingleResolution:
    def test_refresh_single_resolves_analysis_and_ytd_price(self, monkeypatch):
        from unittest.mock import MagicMock
        from datetime import date
        from decimal import Decimal
        from portfoliomaster.core.models import Quote, QuoteStatus

        # Mock YahooAdapter.fetch
        mock_quote = Quote(
            price=Decimal("155.0"),
            previous_close=Decimal("150.0"),
            status=QuoteStatus.FRESH,
            provider="Yahoo",
        )
        monkeypatch.setattr(
            "backend.api.main.YahooAdapter.fetch",
            lambda self, symbols: {symbols[0]: mock_quote},
        )
        # Mock _fetch_historical_quote_for_date
        monkeypatch.setattr(
            "backend.api.main._fetch_historical_quote_for_date",
            lambda symbol, dt: 140.0,
        )
        # Mock _fetch_start_of_year_quote
        monkeypatch.setattr(
            "backend.api.main._fetch_start_of_year_quote",
            lambda symbol, yr: (130.0, date(yr, 1, 2)),
        )

        # Create instrument with analysis_date but NO analysis_reference_price
        client.post("/api/instruments", json={
            "user_ticker": "MSFT_TEST",
            "currency": "USD",
            "fetch_yahoo": False,
            "analysis_date": date.today().isoformat(),
        })

        # Refresh single instrument
        r = client.post("/api/instruments/MSFT_TEST/refresh")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["price"] == 155.0
        assert body.get("analysis_reference_price") == 140.0

        # Verify in positions that analysis reference price is present and variation is computed
        pos_res = client.get("/api/positions")
        assert pos_res.status_code == 200
        pos = next(p for p in pos_res.json()["positions"] if p["user_ticker"] == "MSFT_TEST")
        assert pos["analysis_reference_price"] == 140.0
        assert pos["variation_since_analysis_valid"] is True
        assert pos["variation_since_analysis"] is not None


# ---------------------------------------------------------------------- #
# Ticker Renaming with Clean Metadata Tests (Issue 3)
# ---------------------------------------------------------------------- #

class TestTickerRenameMetadata:
    def test_rename_updates_currency_exchange_and_cleans_quote(self, monkeypatch):
        # Create initial instrument with EUR / SPAIN
        client.post("/api/instruments", json={
            "user_ticker": "OLD_TICKER",
            "company_name": "Old Company SA",
            "currency": "EUR",
            "exchange": "SPAIN",
            "fetch_yahoo": False,
            "manual_price": 50.0,
            "manual_previous_close": 49.0,
        })

        # Update and rename to NEW_TICKER with USD and US exchange and new company name
        r = client.put("/api/instruments/OLD_TICKER", json={
            "new_ticker": "NEW_TICKER",
            "company_name": "New Company Inc",
            "currency": "USD",
            "exchange": "US",
            "latest_price": 120.0,
            "previous_close": 118.0,
        })
        assert r.status_code == 200
        inst = r.json()["instrument"]
        assert inst["user_ticker"] == "NEW_TICKER"
        assert inst["company_name"] == "New Company Inc"
        assert inst["currency"] == "USD"
        assert inst["exchange"] == "US"

        # Verify in /api/positions that old ticker is gone, new ticker exists with new prices and no stale data
        pos_res = client.get("/api/positions")
        tickers = [p["user_ticker"] for p in pos_res.json()["positions"]]
        assert "OLD_TICKER" not in tickers
        assert "NEW_TICKER" in tickers

        pos = next(p for p in pos_res.json()["positions"] if p["user_ticker"] == "NEW_TICKER")
        assert pos["company_name"] == "New Company Inc"
        assert pos["currency"] == "USD"
        assert pos["exchange"] == "US"
        assert pos["latest_price"] == 120.0


# ---------------------------------------------------------------------- #
# Cleanup
# ---------------------------------------------------------------------- #

def teardown_module():
    """Remove the temporary database file."""
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass
