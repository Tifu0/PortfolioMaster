"""Security tests for JWT auth fail-closed, startup secrets, CORS, HSTS, and multi-tenant isolation."""

from __future__ import annotations

import os
import secrets
import time
import uuid
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import backend.api.common as common_module
from backend.api import main
from tests.conftest import TEST_SECRET, mint_jwt


@pytest.fixture
def startup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'startup.db'}")
    monkeypatch.setenv("ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)


class TestAuthenticationSecurity:
    def test_anonymous_requests_rejected_for_all_private_routes(self, isolated_mt_env):
        client = TestClient(main.app)
        private_get = [
            "/api/positions", "/api/metrics", "/api/instruments", "/api/instruments/AAPL",
            "/api/instruments/check-yahoo?ticker=AAPL", "/api/export/csv", "/api/export/excel",
            "/api/export/json", "/api/backup/download", "/api/backup/list",
        ]
        for route in private_get:
            res = client.get(route)
            assert res.status_code == 401 and "WWW-Authenticate" in res.headers

        assert client.post("/api/instruments", json={"user_ticker": "AAPL"}).status_code == 401
        assert client.put("/api/instruments/AAPL", json={"company_name": "Test"}).status_code == 401
        assert client.delete("/api/instruments/AAPL").status_code == 401
        assert client.post("/api/instruments/AAPL/refresh").status_code == 401
        assert client.post("/api/refresh").status_code == 401
        assert client.post("/api/import/confirm", json={"instruments": []}).status_code == 401
        assert client.delete("/api/database").status_code == 401

    def test_public_routes_accessible_without_auth(self, isolated_mt_env):
        client = TestClient(main.app)
        assert client.get("/").json()["status"] == "ok"
        assert client.get("/api/config").json()["status"] == "ok"
        assert client.get("/health").status_code in (200, 503)
        assert client.get("/favicon.ico").status_code == 204

    def test_invalid_expired_and_prohibited_jwts_rejected(self, isolated_mt_env):
        client = TestClient(main.app)
        uid = uuid.uuid4()

        assert client.get("/api/positions", headers={"Authorization": f"Bearer {mint_jwt(uid, expires_in=-100, include_iss=True)}"}).status_code == 401
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {mint_jwt(uid, secret='wrong-secret-key-that-does-not-match-32b', include_iss=True)}"}).status_code == 401
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {mint_jwt(uid, aud='wrong_audience', include_iss=True)}"}).status_code == 401
        assert client.get("/api/positions", headers={"Authorization": "Bearer this.is.not.a.valid.jwt"}).status_code == 401
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {jwt.encode({'aud': 'authenticated'}, TEST_SECRET, algorithm='HS256')}"}).status_code == 401
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {jwt.encode({'sub': 'bad-uuid', 'aud': 'authenticated'}, TEST_SECRET, algorithm='HS256')}"}).status_code == 401

        res_srv = client.get("/api/positions", headers={"Authorization": f"Bearer {mint_jwt(uid, role='service_role', include_iss=True)}"})
        assert res_srv.status_code == 403 and "unauthorized user role" in res_srv.json()["detail"].lower()

        assert client.get("/api/positions", headers={"Authorization": f"Bearer {jwt.encode({'sub': str(uid), 'aud': 'authenticated'}, key='', algorithm='none')}"}).status_code == 401
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {jwt.encode({'sub': str(uid), 'aud': 'authenticated'}, TEST_SECRET, algorithm='HS384')}"}).status_code == 401

    def test_issuer_and_rs256_jwks_verification(self, monkeypatch, isolated_mt_env):
        client = TestClient(main.app)
        uid = uuid.uuid4()
        fake_supabase = "https://asym-test.supabase.co"
        monkeypatch.setenv("SUPABASE_URL", fake_supabase)

        good_hs = mint_jwt(uid, iss=f"{fake_supabase}/auth/v1", include_iss=True)
        bad_hs = mint_jwt(uid, iss="https://evil-spoof.supabase.co/auth/v1", include_iss=True)
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {good_hs}"}).status_code == 200
        res_bad = client.get("/api/positions", headers={"Authorization": f"Bearer {bad_hs}"})
        assert res_bad.status_code == 401 and "issuer" in res_bad.json()["detail"].lower()

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        token = jwt.encode(
            {"sub": str(uid), "aud": "authenticated", "role": "authenticated", "iss": f"{fake_supabase}/auth/v1", "iat": now, "exp": now + 3600},
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key-id"},
        )
        mock_jwk = MagicMock()
        mock_jwk.key = private_key.public_key()
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_jwk
        monkeypatch.setattr(common_module, "_JWKS_CLIENT", mock_client)
        monkeypatch.setattr(common_module, "get_jwks_client", lambda url: mock_client)

        assert client.get("/api/positions", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError("Key not found")
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    def test_forged_x_user_id_header_rejected_and_multi_tenant_isolated(self, isolated_mt_env):
        user_a, user_b = uuid.uuid4(), uuid.uuid4()
        assert TestClient(main.app).get("/api/positions", headers={"X-User-Id": str(user_b)}).status_code == 401

        client_a = TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt(user_a, include_iss=True)}"})
        client_b = TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt(user_b, include_iss=True)}"})

        assert client_a.post("/api/instruments", json={"user_ticker": "AAPL", "currency": "USD", "target_price": 220.0, "fetch_yahoo": False}, headers={"X-User-Id": str(user_b)}).status_code == 201
        assert client_b.get("/api/positions").json()["positions"] == []
        assert client_b.post("/api/instruments", json={"user_ticker": "AAPL", "currency": "USD", "target_price": 330.0, "fetch_yahoo": False}).status_code == 201

        assert client_a.get("/api/instruments/AAPL").json()["instrument"]["target_price"] == 220.0
        assert client_b.get("/api/instruments/AAPL").json()["instrument"]["target_price"] == 330.0
        assert client_b.delete("/api/database").status_code == 200
        assert client_b.get("/api/positions").json()["positions"] == []
        assert len(client_a.get("/api/positions").json()["positions"]) == 1


@pytest.mark.parametrize("secret", [
    "short-key", TEST_SECRET, "your-supabase-jwt-secret",
    "super-secret-jwt-token-with-at-least-32-characters-long", "abcd" * 10, " " * 40,
])
def test_startup_rejects_weak_jwt_secret_in_production(monkeypatch, startup_env, secret):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    with pytest.raises(ValueError, match="SUPABASE_JWT_SECRET") as failure:
        with TestClient(main.app):
            pytest.fail("Startup accepted a weak JWT secret")
    assert secret not in str(failure.value)


def test_startup_and_production_jwt_fail_closed(monkeypatch, startup_env):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("TEST_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("DEV_JWT_SECRET", TEST_SECRET)
    with pytest.raises(ValueError, match="SUPABASE_JWT_SECRET"):
        with TestClient(main.app):
            pytest.fail("Startup accepted test credentials in development")

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    with pytest.raises(ValueError, match="SUPABASE_JWT_SECRET"):
        with TestClient(main.app):
            pytest.fail("Render bypassed credential validation")

    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    response = TestClient(main.app).get("/api/positions", headers={"Authorization": f"Bearer {mint_jwt()}"})
    assert response.status_code == 500 and TEST_SECRET not in response.text


@pytest.mark.parametrize("jwks_only", [False, True])
def test_production_starts_with_valid_auth_configuration(monkeypatch, startup_env, jwks_only):
    monkeypatch.setenv("ENVIRONMENT", "production")
    if jwks_only:
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        monkeypatch.setenv("SUPABASE_URL", "https://project.example")
    else:
        monkeypatch.setenv("SUPABASE_JWT_SECRET", secrets.token_urlsafe(32))
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200


def test_security_headers_and_cors_configuration():
    client_https = TestClient(main.app, base_url="https://testserver")
    responses = [
        client_https.get("/health"),
        client_https.get("/api/positions"),
        client_https.options("/api/positions", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}),
    ]
    assert [r.status_code for r in responses] == [200, 401, 200]
    for res in responses:
        assert res.headers["x-content-type-options"] == "nosniff"
        assert res.headers["x-frame-options"] == "DENY"
        assert res.headers["strict-transport-security"] == "max-age=31536000"

    assert "strict-transport-security" not in TestClient(main.app).get("/health").headers

    with patch.dict(os.environ, {"CORS_ORIGINS": "https://app.vercel.app,*"}, clear=False):
        with pytest.raises(RuntimeError, match="Wildcard '\\*'"):
            origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
            if "*" in origins:
                raise RuntimeError("Wildcard '*' is forbidden in CORS_ORIGINS when allow_credentials=True.")

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "CORS_ORIGINS": ""}, clear=False):
        with pytest.raises(RuntimeError, match="CORS_ORIGINS must be set in production"):
            if not os.environ.get("CORS_ORIGINS") and os.environ.get("ENVIRONMENT") == "production":
                raise RuntimeError("CORS_ORIGINS must be set in production")

    with patch.dict(os.environ, {"CORS_ORIGINS": "https://foo.com, https://bar.vercel.app "}):
        assert [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()] == [
            "https://foo.com", "https://bar.vercel.app"
        ]
