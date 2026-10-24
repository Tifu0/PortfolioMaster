"""Integration tests for Backup & Export API endpoints."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import openpyxl
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["PORTFOLIOMASTER_DB_PATH"] = _tmp_db.name
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

_tmp_backup_dir = tempfile.mkdtemp(prefix="pm_backups_")
os.environ["PORTFOLIOMASTER_BACKUP_DIR"] = _tmp_backup_dir

from fastapi.testclient import TestClient
from portfoliomaster.db.connection import init_db

init_db()

import uuid
import jwt
from backend.api.main import app  # noqa: E402

TEST_USER_ID = uuid.UUID("c6dd2d21-c378-40f4-9848-5680db9fec27")
TEST_JWT_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET

def _mint_test_token(user_id: uuid.UUID = TEST_USER_ID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "role": "authenticated"},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

client = TestClient(app, headers={"Authorization": f"Bearer {_mint_test_token()}"})


@pytest.fixture(autouse=True)
def _clean_db():
    client.delete("/api/database")
    yield


class TestExportEndpoints:
    def test_export_csv_empty_and_populated(self):
        # Insert a position with all ground-truth fields
        client.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "company_name": "Apple Inc.",
            "currency": "USD",
            "target_price": 220.0,
            "analysis_reference_price": 180.0,
            "analysis_date": "2024-05-15",
            "start_of_year_price": 185.0,
            "start_of_year_date": "2026-01-02",
            "comment": "Gran flujo de caja libre",
            "fetch_yahoo": False,
            "manual_price": 195.0,
            "manual_previous_close": 190.0,
        })

        r = client.get("/api/export/csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "Content-Disposition" in r.headers
        assert "portfoliomaster_export_" in r.headers["Content-Disposition"]
        assert r.headers["Content-Disposition"].endswith('.csv"')

        csv_text = r.text
        assert "AAPL" in csv_text
        assert "Apple Inc." in csv_text
        assert "Gran flujo de caja libre" in csv_text
        assert "220.00" in csv_text

    def test_export_excel(self):
        client.post("/api/instruments", json={
            "user_ticker": "MSFT",
            "company_name": "Microsoft Corp.",
            "currency": "USD",
            "target_price": 450.0,
            "fetch_yahoo": False,
        })

        r = client.get("/api/export/excel")
        assert r.status_code == 200
        assert "spreadsheetml.sheet" in r.headers["content-type"]
        assert "portfoliomaster_export_" in r.headers["Content-Disposition"]
        assert r.headers["Content-Disposition"].endswith('.xlsx"')

        # Verify openpyxl can read the returned bytes
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        ws = wb.active
        assert ws.title == "Watchlist"
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) >= 2  # Header + at least 1 data row
        assert "Ticker" in rows[0]
        tickers = [row[0] for row in rows[1:]]
        assert "MSFT" in tickers

    def test_export_json(self):
        client.post("/api/instruments", json={
            "user_ticker": "GOOGL",
            "company_name": "Alphabet Inc.",
            "currency": "USD",
            "target_price": 190.0,
            "fetch_yahoo": False,
        })

        r = client.get("/api/export/json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        assert "portfoliomaster_backup_" in r.headers["Content-Disposition"]

        data = r.json()
        assert data["version"] == "1.0"
        assert data["total_positions"] == 1
        assert len(data["instruments"]) == 1
        assert data["instruments"][0]["user_ticker"] == "GOOGL"

    def test_round_trip_via_import_preview(self):
        """Export watchlist through API and pass directly into /api/import/preview."""
        client.post("/api/instruments", json={
            "user_ticker": "SAN",
            "company_name": "Banco Santander",
            "currency": "EUR",
            "target_price": 5.20,
            "analysis_reference_price": 4.10,
            "analysis_date": "2025-04-10",
            "start_of_year_price": 4.05,
            "start_of_year_date": "2026-01-02",
            "comment": "Dividendo bancario robusto",
            "fetch_yahoo": False,
        })

        # 1. Test CSV export -> import preview
        r_csv = client.get("/api/export/csv")
        assert r_csv.status_code == 200

        r_prev_csv = client.post(
            "/api/import/preview",
            files={"file": ("export.csv", io.BytesIO(r_csv.content), "text/csv")},
        )
        assert r_prev_csv.status_code == 200
        prev_data_csv = r_prev_csv.json()
        assert prev_data_csv["errors"] == []
        assert prev_data_csv["valid_count"] == 1
        imported_inst = prev_data_csv["instruments"][0]
        assert imported_inst["user_ticker"] == "SAN"
        assert imported_inst["comment"] == "Dividendo bancario robusto"
        assert imported_inst["target_price"] == 5.20
        assert imported_inst["analysis_reference_price"] == 4.10
        assert imported_inst["start_of_year_price"] == 4.05

        # 2. Test Excel export -> import preview
        r_xlsx = client.get("/api/export/excel")
        assert r_xlsx.status_code == 200

        r_prev_xlsx = client.post(
            "/api/import/preview",
            files={"file": ("export.xlsx", io.BytesIO(r_xlsx.content), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r_prev_xlsx.status_code == 200
        prev_data_xlsx = r_prev_xlsx.json()
        assert prev_data_xlsx["errors"] == []
        assert prev_data_xlsx["valid_count"] == 1
        imported_xlsx = prev_data_xlsx["instruments"][0]
        assert imported_xlsx["user_ticker"] == "SAN"
        assert imported_xlsx["comment"] == "Dividendo bancario robusto"
        assert imported_xlsx["target_price"] == 5.20


class TestBackupAndRestoreEndpoints:
    def test_backup_download(self):
        client.post("/api/instruments", json={
            "user_ticker": "NVDA",
            "currency": "USD",
            "fetch_yahoo": False,
        })

        r = client.get("/api/backup/download")
        assert r.status_code == 200
        assert "application/x-sqlite3" in r.headers["content-type"]
        assert "portfoliomaster_backup_" in r.headers["Content-Disposition"]
        assert r.headers["Content-Disposition"].endswith('.db"')
        # SQLite file header check
        assert r.content.startswith(b"SQLite format 3\x00")

    def test_backup_restore_sqlite_file(self):
        client.post("/api/instruments", json={
            "user_ticker": "AMD",
            "company_name": "Advanced Micro Devices",
            "currency": "USD",
            "fetch_yahoo": False,
        })

        # Download snapshot bytes
        backup_bytes = client.get("/api/backup/download").content

        # Wipe DB
        client.delete("/api/database")
        assert client.get("/api/instruments").json()["count"] == 0

        # Restore from uploaded .db
        r_restore = client.post(
            "/api/backup/restore",
            files={"file": ("backup.db", io.BytesIO(backup_bytes), "application/x-sqlite3")},
        )
        assert r_restore.status_code == 200
        body = r_restore.json()
        assert body["status"] == "ok"
        assert body["restored_instruments"] == 1

        # Verify AMD exists in DB
        r_get = client.get("/api/instruments/AMD")
        assert r_get.status_code == 200
        assert r_get.json()["company_name"] == "Advanced Micro Devices"

    def test_backup_restore_json_file(self):
        json_content = """{
            "version": "1.0",
            "total_positions": 1,
            "instruments": [
                {
                    "user_ticker": "IBM",
                    "company_name": "International Business Machines",
                    "currency": "USD",
                    "target_price": 250.0,
                    "comment": "Restored via JSON",
                    "active": true
                }
            ]
        }"""

        r = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(json_content.encode("utf-8")), "application/json")},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["restored_instruments"] == 1

        # Check DB
        r_ibm = client.get("/api/instruments/IBM")
        assert r_ibm.status_code == 200
        assert r_ibm.json()["company_name"] == "International Business Machines"
        assert r_ibm.json()["comment"] == "Restored via JSON"

    def test_backup_restore_corrupted_file(self):
        corrupted_bytes = b"NOT_A_VALID_SQLITE_OR_JSON"
        r = client.post(
            "/api/backup/restore",
            files={"file": ("corrupt.db", io.BytesIO(corrupted_bytes), "application/x-sqlite3")},
        )
        assert r.status_code == 400

    def test_backup_list_and_restore_local(self):
        # Trigger an automatic safety backup by wiping database with items
        client.post("/api/instruments", json={
            "user_ticker": "QCOM",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        client.delete("/api/database")

        r_list = client.get("/api/backup/list")
        assert r_list.status_code == 200
        backups = r_list.json()["backups"]
        assert len(backups) >= 1
        latest_filename = backups[0]["filename"]

        # Restore from this local backup
        r_restore = client.post(f"/api/backup/restore/{latest_filename}")
        assert r_restore.status_code == 200
        assert r_restore.json()["status"] == "ok"

        # Verify QCOM restored
        assert client.get("/api/instruments/QCOM").status_code == 200

    def test_restore_local_path_traversal_and_invalid_rejected(self):
        # 1. Invalid extension
        r1 = client.post("/api/backup/restore/invalid_file.txt")
        assert r1.status_code == 400

        # 2. Path traversal
        r2 = client.post("/api/backup/restore/..%2F..%2Fsecret.db")
        assert r2.status_code in (400, 404)

        # 3. Non-existent file
        r3 = client.post("/api/backup/restore/portfolio_backup_nonexistent_9999.db")
        assert r3.status_code == 404


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass
