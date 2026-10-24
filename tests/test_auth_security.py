"""Comprehensive security and tenant isolation tests for PortfolioMaster API.

Verifies:
1. All private endpoints fail closed with HTTP 401 for anonymous access.
2. Public routes remain accessible without credentials.
3. Expired, invalid signature, wrong audience, and malformed JWTs return HTTP 401.
4. Forged X-User-Id header cannot bypass authentication or change authenticated tenant.
5. Strict tenant isolation between User A and User B across CRUD, positions, metrics, and wipe.
"""

from __future__ import annotations

import os
import time
import uuid
import jwt
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from portfoliomaster.db.schema import Base

TEST_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
os.environ["SUPABASE_JWT_SECRET"] = TEST_SECRET


def mint_token(
    user_id: uuid.UUID,
    expires_in: int = 3600,
    secret: str = TEST_SECRET,
    aud: str = "authenticated",
    role: str = "authenticated",
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "aud": aud,
        "role": role,
        "iat": now,
        "exp": now + expires_in,
        "email": f"user-{str(user_id)[:8]}@test.com",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
    test_db = tmp_path / "test_auth_security.db"
    db_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    
    # Reset cached engine in session.py to force using new test_db
    import portfoliomaster.db.session as session_module
    session_module._ENGINE = None
    session_module._SESSION_FACTORY = None

    # Initialize multi-tenant tables on the test db
    eng = session_module.get_engine(db_url)
    Base.metadata.create_all(eng)
    yield
    session_module._ENGINE = None
    session_module._SESSION_FACTORY = None


class TestAuthenticationSecurity:
    """Security boundary tests verifying mandatory authentication."""

    def test_anonymous_requests_rejected_for_all_private_routes(self):
        client = TestClient(app)

        private_get_routes = [
            "/api/positions",
            "/api/metrics",
            "/api/instruments",
            "/api/instruments/AAPL",
            "/api/instruments/check-yahoo?ticker=AAPL",
            "/api/export/csv",
            "/api/export/excel",
            "/api/export/json",
            "/api/backup/download",
            "/api/backup/list",
        ]

        for route in private_get_routes:
            res = client.get(route)
            assert res.status_code == 401, f"Expected 401 for GET {route}, got {res.status_code}"
            assert "WWW-Authenticate" in res.headers, f"Missing WWW-Authenticate header for GET {route}"

        # Private POST/PUT/DELETE routes
        assert client.post("/api/instruments", json={"user_ticker": "AAPL"}).status_code == 401
        assert client.put("/api/instruments/AAPL", json={"company_name": "Test"}).status_code == 401
        assert client.delete("/api/instruments/AAPL").status_code == 401
        assert client.post("/api/instruments/AAPL/refresh").status_code == 401
        assert client.post("/api/refresh").status_code == 401
        assert client.post("/api/import/confirm", json={"instruments": []}).status_code == 401
        assert client.delete("/api/database").status_code == 401

    def test_public_routes_accessible_without_auth(self):
        client = TestClient(app)

        r_root = client.get("/")
        assert r_root.status_code == 200
        assert r_root.json()["status"] == "ok"

        r_config = client.get("/api/config")
        assert r_config.status_code == 200
        assert r_config.json()["status"] == "ok"

        r_health = client.get("/health")
        assert r_health.status_code in (200, 503)

        r_favicon = client.get("/favicon.ico")
        assert r_favicon.status_code == 204

    def test_invalid_and_expired_jwts_rejected(self):
        client = TestClient(app)
        user_id = uuid.uuid4()

        # Expired token
        expired_token = mint_token(user_id, expires_in=-100)
        res_exp = client.get("/api/positions", headers={"Authorization": f"Bearer {expired_token}"})
        assert res_exp.status_code == 401
        assert "expired" in res_exp.json()["detail"].lower()

        # Wrong secret signature
        forged_token = mint_token(user_id, secret="wrong-secret-key-that-does-not-match-32b")
        res_sig = client.get("/api/positions", headers={"Authorization": f"Bearer {forged_token}"})
        assert res_sig.status_code == 401

        # Wrong audience
        wrong_aud_token = mint_token(user_id, aud="wrong_audience")
        res_aud = client.get("/api/positions", headers={"Authorization": f"Bearer {wrong_aud_token}"})
        assert res_aud.status_code == 401

        # Malformed token
        res_mal = client.get("/api/positions", headers={"Authorization": "Bearer this.is.not.a.valid.jwt"})
        assert res_mal.status_code == 401

        # Missing sub claim
        no_sub_token = jwt.encode({"aud": "authenticated"}, TEST_SECRET, algorithm="HS256")
        res_sub = client.get("/api/positions", headers={"Authorization": f"Bearer {no_sub_token}"})
        assert res_sub.status_code == 401

        # Non-UUID sub claim
        bad_sub_token = jwt.encode({"sub": "not-a-valid-uuid", "aud": "authenticated"}, TEST_SECRET, algorithm="HS256")
        res_bad = client.get("/api/positions", headers={"Authorization": f"Bearer {bad_sub_token}"})
        assert res_bad.status_code == 401

        # Prohibited role: service_role rejected on user-facing routes
        service_role_token = mint_token(user_id, role="service_role")
        res_srv = client.get("/api/positions", headers={"Authorization": f"Bearer {service_role_token}"})
        assert res_srv.status_code == 403
        assert "unauthorized user role" in res_srv.json()["detail"].lower()

        # Prohibited algorithm: none
        none_alg_token = jwt.encode({"sub": str(user_id), "aud": "authenticated"}, key="", algorithm="none")
        res_none = client.get("/api/positions", headers={"Authorization": f"Bearer {none_alg_token}"})
        assert res_none.status_code == 401
        assert "unsupported" in res_none.json()["detail"].lower()

        # Prohibited algorithm: HS384 / arbitrary
        hs384_token = jwt.encode({"sub": str(user_id), "aud": "authenticated"}, TEST_SECRET, algorithm="HS384")
        res_384 = client.get("/api/positions", headers={"Authorization": f"Bearer {hs384_token}"})
        assert res_384.status_code == 401
        assert "unsupported" in res_384.json()["detail"].lower()

    def test_issuer_verification_when_supabase_url_configured(self, monkeypatch):
        client = TestClient(app)
        user_id = uuid.uuid4()
        fake_supabase = "https://my-test-proj.supabase.co"
        monkeypatch.setenv("SUPABASE_URL", fake_supabase)

        # Token with matching issuer passes
        now = int(time.time())
        good_payload = {
            "sub": str(user_id),
            "aud": "authenticated",
            "role": "authenticated",
            "iss": f"{fake_supabase}/auth/v1",
            "iat": now,
            "exp": now + 3600,
        }
        good_token = jwt.encode(good_payload, TEST_SECRET, algorithm="HS256")
        res_good = client.get("/api/positions", headers={"Authorization": f"Bearer {good_token}"})
        assert res_good.status_code == 200

        # Token with mismatched issuer fails with 401
        bad_payload = dict(good_payload, iss="https://evil-spoof.supabase.co/auth/v1")
        bad_token = jwt.encode(bad_payload, TEST_SECRET, algorithm="HS256")
        res_bad = client.get("/api/positions", headers={"Authorization": f"Bearer {bad_token}"})
        assert res_bad.status_code == 401
        assert "issuer" in res_bad.json()["detail"].lower()

    def test_asymmetric_rs256_verification(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from unittest.mock import MagicMock
        import backend.api.common as common_module

        # Generate disposable RSA keypair
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        client = TestClient(app)
        user_id = uuid.uuid4()
        fake_supabase = "https://asym-test.supabase.co"
        monkeypatch.setenv("SUPABASE_URL", fake_supabase)

        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "aud": "authenticated",
            "role": "authenticated",
            "iss": f"{fake_supabase}/auth/v1",
            "iat": now,
            "exp": now + 3600,
        }
        token = jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key-id"})

        # Mock PyJWKClient to return this public key
        mock_jwk = MagicMock()
        mock_jwk.key = public_key
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_jwk

        monkeypatch.setattr(common_module, "_JWKS_CLIENT", mock_client)
        monkeypatch.setattr(common_module, "get_jwks_client", lambda url: mock_client)

        res = client.get("/api/positions", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200

        # If JWKS key fails to resolve, fails with 401
        mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("Key not found")
        res_err = client.get("/api/positions", headers={"Authorization": f"Bearer {token}"})
        assert res_err.status_code == 401

    def test_forged_x_user_id_header_rejected(self):
        client = TestClient(app)
        attacker_id = uuid.uuid4()
        victim_id = uuid.uuid4()

        # Attempting X-User-Id without valid token fails with 401
        res_bypass = client.get("/api/positions", headers={"X-User-Id": str(victim_id)})
        assert res_bypass.status_code == 401

        # Supplying valid token for Attacker with X-User-Id of Victim must still scope to Attacker
        attacker_token = mint_token(attacker_id)
        attacker_client = TestClient(app, headers={"Authorization": f"Bearer {attacker_token}"})

        # Attacker creates AAPL
        attacker_client.post(
            "/api/instruments",
            json={"user_ticker": "AAPL_ATTACK", "currency": "USD", "fetch_yahoo": False},
            headers={"X-User-Id": str(victim_id)},
        )

        # Victim inspects positions
        victim_token = mint_token(victim_id)
        victim_client = TestClient(app, headers={"Authorization": f"Bearer {victim_token}"})
        victim_pos = victim_client.get("/api/positions").json()["positions"]

        # If X-User-Id was respected, victim would see AAPL_ATTACK. It must NOT be there!
        victim_tickers = [p["user_ticker"] for p in victim_pos]
        assert "AAPL_ATTACK" not in victim_tickers


class TestMultiTenantIsolation:
    """End-to-end multi-tenant isolation tests."""

    def test_two_users_isolated_instruments_and_positions(self):
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        token_a = mint_token(user_a)
        token_b = mint_token(user_b)

        client_a = TestClient(app, headers={"Authorization": f"Bearer {token_a}"})
        client_b = TestClient(app, headers={"Authorization": f"Bearer {token_b}"})

        # User A creates AAPL with target 220
        res_create_a = client_a.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "company_name": "Apple User A",
            "currency": "USD",
            "target_price": 220.0,
            "fetch_yahoo": False,
        })
        assert res_create_a.status_code in (200, 201)

        # User B queries positions: must not see User A's AAPL
        pos_b = client_b.get("/api/positions").json()["positions"]
        assert len([p for p in pos_b if p["user_ticker"] == "AAPL"]) == 0

        # User B creates AAPL with target 330
        res_create_b = client_b.post("/api/instruments", json={
            "user_ticker": "AAPL",
            "company_name": "Apple User B",
            "currency": "USD",
            "target_price": 330.0,
            "fetch_yahoo": False,
        })
        assert res_create_b.status_code in (200, 201)

        # Verify User A still has their target 220
        inst_a = client_a.get("/api/instruments/AAPL").json()
        assert inst_a["target_price"] == 220.0

        # Verify User B has their target 330
        inst_b = client_b.get("/api/instruments/AAPL").json()
        assert inst_b["target_price"] == 330.0

        # User B wipes their database
        wipe_res = client_b.delete("/api/database")
        assert wipe_res.status_code == 200

        # User B has 0 positions
        assert len(client_b.get("/api/positions").json()["positions"]) == 0

        # User A still has their AAPL position intact!
        pos_a_after = client_a.get("/api/positions").json()["positions"]
        assert len([p for p in pos_a_after if p["user_ticker"] == "AAPL"]) == 1
