"""Security tests for input bounds, formula injection sanitization, restore safety, and error masking."""

from __future__ import annotations

import io
import json
import secrets
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.api import main
from backend.api.common import validate_auth_configuration
from backend.api.routers import import_export, instruments
from portfoliomaster.backup.exporters import _sanitize_formula
from portfoliomaster.ingest.parser import parse_spreadsheet
from tests.conftest import mint_jwt


class TestBackupRestoreSafetyRegression:
    def _seed_user_instruments(self, client: TestClient):
        client.post("/api/instruments", json={"user_ticker": "AAPL", "company_name": "Apple Inc.", "currency": "USD", "fetch_yahoo": False})
        client.post("/api/instruments", json={"user_ticker": "MSFT", "company_name": "Microsoft Corp.", "currency": "USD", "fetch_yahoo": False})

    def test_malformed_and_invalid_backup_payloads_preserve_data(self, isolated_mt_env):
        client = TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
        self._seed_user_instruments(client)

        invalid_cases = [
            (b"{}", 400, "missing required 'instruments'"),
            (json.dumps({"version": "1.0", "app": "watchlistTracker"}).encode(), 400, "missing required 'instruments'"),
            (json.dumps({"version": "1.0", "instruments": "not_a_list"}).encode(), 400, "must be a list"),
            (b'{"version": "1.0", "instruments": [{"user_ticker": "AAPL"', 400, "invalid json"),
            (json.dumps({"version": "1.0", "instruments": [{"user_ticker": "GOOGL"}, {"user_ticker": "googl"}]}).encode(), 400, "duplicate ticker"),
            (json.dumps({"version": "1.0", "instruments": [{"user_ticker": "NVDA", "analysis_date": "bad-date"}]}).encode(), 400, "invalid analysis_date"),
            (json.dumps({"version": "1.0", "instruments": [{"user_ticker": "NVDA", "target_price": -50.0}]}).encode(), 400, "target_price"),
            (json.dumps({"version": "1.0", "instruments": [{"user_ticker": f"T{i}"} for i in range(501)]}).encode(), 400, "500"),
            (json.dumps({"version": "1.0", "instruments": [{"user_ticker": "AAPL", "target_price": "not-a-decimal"}]}).encode(), 400, ""),
        ]
        for raw_bytes, expected_status, expected_msg in invalid_cases:
            res = client.post(
                "/api/backup/restore",
                files={"file": ("backup.json", io.BytesIO(raw_bytes), "application/json")},
            )
            assert res.status_code == expected_status
            if expected_msg:
                assert expected_msg in res.json()["detail"].lower()
            assert client.get("/api/instruments").json()["count"] == 2

        oversized = client.post(
            "/api/backup/restore",
            files={"file": ("huge.json", io.BytesIO(b" " * (11 * 1024 * 1024)), "application/json")},
        )
        assert oversized.status_code == 413 and client.get("/api/instruments").json()["count"] == 2

    def test_valid_empty_and_populated_backup_and_tenant_isolation(self, isolated_mt_env):
        client_a = TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
        client_b = TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})

        self._seed_user_instruments(client_a)
        client_b.post("/api/instruments", json={"user_ticker": "TSLA", "company_name": "Tesla Inc.", "currency": "USD", "fetch_yahoo": False})

        empty_payload = json.dumps({"version": "1.0", "app": "watchlistTracker", "instruments": []}).encode()
        res_empty = client_a.post("/api/backup/restore", files={"file": ("backup.json", io.BytesIO(empty_payload), "application/json")})
        assert res_empty.status_code == 200 and res_empty.json()["restored_count"] == 0
        assert client_a.get("/api/instruments").json()["count"] == 0

        pop_payload = json.dumps({
            "version": "1.0",
            "app": "watchlistTracker",
            "instruments": [
                {"user_ticker": "AMZN", "company_name": "Amazon.com Inc.", "currency": "USD", "target_price": 240.0, "active": True},
                {"user_ticker": "BME:ITX", "company_name": "Inditex S.A.", "currency": "EUR", "target_price": 50.0, "active": True},
            ],
        }).encode()
        res_pop = client_a.post("/api/backup/restore", files={"file": ("backup.json", io.BytesIO(pop_payload), "application/json")})
        assert res_pop.status_code == 200 and res_pop.json()["restored_count"] == 2
        assert client_b.get("/api/instruments").json()["instruments"][0]["user_ticker"] == "TSLA"


def test_production_exception_handler_masks_internal_errors(monkeypatch, isolated_mt_env):
    monkeypatch.setenv("ENVIRONMENT", "production")

    class IntegrityError(Exception):
        pass

    monkeypatch.setattr(instruments, "normalize", lambda *_a, **_kw: (_ for _ in ()).throw(IntegrityError('duplicate key "secret_table_col" DETAIL: Key (x)=(secret)')))
    client = TestClient(main.app, raise_server_exceptions=False, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    res = client.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})
    assert res.status_code == 500
    assert "secret_table_col" not in res.text.lower() and "duplicate key" not in res.text.lower()


def test_jwt_requires_explicit_authenticated_role_and_prod_supabase_url(monkeypatch, isolated_mt_env):
    user_id = uuid.uuid4()
    no_role_token = mint_jwt(user_id, include_role=False, include_iss=True)
    assert TestClient(main.app, headers={"Authorization": f"Bearer {no_role_token}"}).get("/api/instruments").status_code == 403

    prod_secret = secrets.token_urlsafe(32)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", prod_secret)
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        validate_auth_configuration()

    valid_token = jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 3600},
        prod_secret,
        algorithm="HS256",
    )
    assert TestClient(main.app, headers={"Authorization": f"Bearer {valid_token}"}).get("/api/instruments").status_code == 500


def test_sanitize_formula_neutralizes_whitespace_and_control_prefixes():
    for payload in ("=1+1", "+cmd", "-1+1", "@SUM(1,2)", "\t=1+1", "\r+1", "  =SUM(A1)", " \t @cmd"):
        assert _sanitize_formula(payload).startswith("'")


def test_xlsx_row_limit_and_streamed_import_upload_bounds(monkeypatch, isolated_mt_env, tmp_path):
    xlsx_path = tmp_path / "too_many.xlsx"
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append(["Ticker", "Name"])
    for idx in range(12):
        ws.append([f"T{idx}", f"Company {idx}"])
    wb.save(xlsx_path)

    df, err = parse_spreadsheet(str(xlsx_path), "too_many.xlsx", max_rows=10)
    assert df is None and err is not None and "10" in err

    monkeypatch.setattr(import_export, "MAX_UPLOAD_BYTES", 64)
    client = TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    oversized = b"ticker,company_name\n" + (b"AAPL,Apple\n" * 20)
    assert client.post("/api/import/preview", files={"file": ("big.csv", oversized, "text/csv")}).status_code == 413


def test_import_confirm_sqlite_returns_400_when_zero_committed_with_errors(sqlite_api_client, monkeypatch):
    monkeypatch.setattr(import_export, "upsert_instrument", lambda _inst: (_ for _ in ()).throw(RuntimeError("boom")))
    res = sqlite_api_client.post("/api/import/confirm", json={"instruments": [{"user_ticker": "AAPL"}]})
    assert res.status_code == 400
