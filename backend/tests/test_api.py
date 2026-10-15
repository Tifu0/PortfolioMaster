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
        })

        r = client.get("/api/positions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1

        pos = body["positions"][0]
        assert pos["user_ticker"] == "AAPL"
        assert pos["latest_price"] == 150.0
        assert pos["previous_close"] == 148.0

        # Computed columns must be present and valid
        assert pos["daily_variation_valid"] is True
        assert isinstance(pos["daily_variation"], float)
        assert pos["variation_since_analysis_valid"] is True
        assert pos["decline_to_target_valid"] is True

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

    def test_update_not_found(self):
        r = client.put("/api/instruments/NOPE", json={"comment": "x"})
        assert r.status_code == 404


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
# Cleanup
# ---------------------------------------------------------------------- #

def teardown_module():
    """Remove the temporary database file."""
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass
