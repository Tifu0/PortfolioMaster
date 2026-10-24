"""Comprehensive regression tests for backup & restore data safety.

Verifies:
1. Uploading {} or missing 'instruments' never wipes existing watchlist data.
2. Malformed JSON, non-list instruments, invalid rows, negative prices, and bad dates reject with HTTP 400.
3. Duplicate tickers in the backup payload reject with HTTP 400.
4. Oversized backup files reject with HTTP 413.
5. In all rejection cases, existing rows are 100% preserved.
6. Valid intentionally empty backup (with 'version' or 'app') cleanly clears rows as intended.
7. Valid populated backup successfully restores.
8. Multi-tenant isolation: User A restore never touches User B's records.
"""

from __future__ import annotations

import io
import json
import time
import uuid
import jwt
import pytest
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


@pytest.fixture(autouse=True)
def setup_multi_tenant_db(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
    test_db = tmp_path / "test_backup_safety.db"
    db_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    session_module._ENGINE = None
    session_module._SESSION_FACTORY = None

    eng = session_module.get_engine(db_url)
    Base.metadata.create_all(eng)
    yield
    session_module._ENGINE = None
    session_module._SESSION_FACTORY = None


class TestBackupRestoreSafetyRegression:

    def _seed_user_instruments(self, client: TestClient):
        client.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "company_name": "Apple Inc.",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        client.post("/api/instruments", json={
            "user_ticker": "MSFT",
            "company_name": "Microsoft Corp.",
            "currency": "USD",
            "fetch_yahoo": False,
        })

    def test_empty_json_object_rejected_and_preserves_existing_data(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        # Seed existing data
        self._seed_user_instruments(client)
        assert client.get("/api/instruments").json()["count"] == 2

        # Upload empty object {}
        empty_obj_json = b"{}"
        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(empty_obj_json), "application/json")},
        )
        assert res.status_code == 400
        assert "missing required 'instruments'" in res.json()["detail"].lower()

        # Existing 2 instruments must NOT be deleted!
        res_after = client.get("/api/instruments")
        assert res_after.status_code == 200
        assert res_after.json()["count"] == 2
        tickers = [i["user_ticker"] for i in res_after.json()["instruments"]]
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_missing_instruments_key_rejected(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        payload = json.dumps({"version": "1.0", "app": "watchlistTracker"}).encode("utf-8")
        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(payload), "application/json")},
        )
        assert res.status_code == 400
        assert "missing required 'instruments'" in res.json()["detail"].lower()

        # Data preserved
        assert client.get("/api/instruments").json()["count"] == 2

    def test_non_list_instruments_rejected(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        payload = json.dumps({"version": "1.0", "instruments": "not_a_list"}).encode("utf-8")
        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(payload), "application/json")},
        )
        assert res.status_code == 400
        assert "must be a list" in res.json()["detail"].lower()

        # Data preserved
        assert client.get("/api/instruments").json()["count"] == 2

    def test_malformed_json_rejected(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        malformed_bytes = b'{"version": "1.0", "instruments": [{"user_ticker": "AAPL"'  # Unclosed JSON
        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(malformed_bytes), "application/json")},
        )
        assert res.status_code == 400
        assert "invalid json" in res.json()["detail"].lower()

        # Data preserved
        assert client.get("/api/instruments").json()["count"] == 2

    def test_duplicate_tickers_in_backup_rejected(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        payload = json.dumps({
            "version": "1.0",
            "instruments": [
                {"user_ticker": "GOOGL", "currency": "USD"},
                {"user_ticker": "googl", "currency": "USD"},  # Duplicate case-insensitive
            ]
        }).encode("utf-8")

        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(payload), "application/json")},
        )
        assert res.status_code == 400
        assert "duplicate ticker" in res.json()["detail"].lower()

        # Data preserved
        assert client.get("/api/instruments").json()["count"] == 2

    def test_invalid_numerical_or_date_value_rejected(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        # Invalid date
        payload_bad_date = json.dumps({
            "version": "1.0",
            "instruments": [
                {"user_ticker": "NVDA", "currency": "USD", "analysis_date": "not-a-valid-date"}
            ]
        }).encode("utf-8")
        res_date = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(payload_bad_date), "application/json")},
        )
        assert res_date.status_code == 400
        assert "invalid analysis_date" in res_date.json()["detail"].lower()
        assert client.get("/api/instruments").json()["count"] == 2

        # Negative price
        payload_neg = json.dumps({
            "version": "1.0",
            "instruments": [
                {"user_ticker": "NVDA", "currency": "USD", "target_price": -50.0}
            ]
        }).encode("utf-8")
        res_neg = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(payload_neg), "application/json")},
        )
        assert res_neg.status_code == 400
        assert "target_price" in res_neg.json()["detail"].lower()
        assert client.get("/api/instruments").json()["count"] == 2

    def test_oversized_backup_file_rejected(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        # 11 MB payload
        huge_content = b" " * (11 * 1024 * 1024)
        res = client.post(
            "/api/backup/restore",
            files={"file": ("huge.json", io.BytesIO(huge_content), "application/json")},
        )
        assert res.status_code == 413
        assert client.get("/api/instruments").json()["count"] == 2

    def test_valid_intentionally_empty_backup_clears_data(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)
        assert client.get("/api/instruments").json()["count"] == 2

        # Valid explicitly shaped export with instruments: []
        empty_valid_payload = json.dumps({
            "version": "1.0",
            "app": "watchlistTracker",
            "total_instruments": 0,
            "instruments": [],
        }).encode("utf-8")

        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(empty_valid_payload), "application/json")},
        )
        assert res.status_code == 200
        assert res.json()["restored_count"] == 0
        assert client.get("/api/instruments").json()["count"] == 0

    def test_valid_populated_backup_restores_and_replaces(self):
        user_id = uuid.uuid4()
        token = mint_token(user_id)
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        self._seed_user_instruments(client)

        valid_payload = json.dumps({
            "version": "1.0",
            "app": "watchlistTracker",
            "instruments": [
                {
                    "user_ticker": "AMZN",
                    "company_name": "Amazon.com Inc.",
                    "currency": "USD",
                    "target_price": 240.0,
                    "active": True,
                },
                {
                    "user_ticker": "BME:ITX",
                    "company_name": "Inditex S.A.",
                    "currency": "EUR",
                    "target_price": 50.0,
                    "active": True,
                },
            ],
        }).encode("utf-8")

        res = client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(valid_payload), "application/json")},
        )
        assert res.status_code == 200
        assert res.json()["restored_count"] == 2

        res_inst = client.get("/api/instruments")
        assert res_inst.json()["count"] == 2
        tickers = [i["user_ticker"] for i in res_inst.json()["instruments"]]
        assert "AMZN" in tickers
        assert "BME:ITX" in tickers
        # Old rows (AAPL, MSFT) should be replaced
        assert "AAPL" not in tickers

    def test_two_users_isolated_during_restore(self):
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        token_a = mint_token(user_a)
        token_b = mint_token(user_b)

        client_a = TestClient(app, headers={"Authorization": f"Bearer {token_a}"})
        client_b = TestClient(app, headers={"Authorization": f"Bearer {token_b}"})

        # User B creates TSLA
        client_b.post("/api/instruments", json={
            "user_ticker": "TSLA",
            "company_name": "Tesla Inc.",
            "currency": "USD",
            "fetch_yahoo": False,
        })
        assert client_b.get("/api/instruments").json()["count"] == 1

        # User A restores a backup containing AAPL
        payload_a = json.dumps({
            "version": "1.0",
            "instruments": [{"user_ticker": "AAPL", "currency": "USD"}]
        }).encode("utf-8")

        res_a = client_a.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(payload_a), "application/json")},
        )
        assert res_a.status_code == 200

        # User A sees only AAPL
        assert client_a.get("/api/instruments").json()["count"] == 1
        assert client_a.get("/api/instruments").json()["instruments"][0]["user_ticker"] == "AAPL"

        # User B's TSLA must remain 100% untouched!
        b_insts = client_b.get("/api/instruments").json()
        assert b_insts["count"] == 1
        assert b_insts["instruments"][0]["user_ticker"] == "TSLA"
