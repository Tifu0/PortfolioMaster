"""Regression coverage for worker isolation, database pooling, and HTTP security."""

import asyncio
import secrets
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select

from backend.api import main
from backend.api.routers import backup, instruments, refresh
from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db import session as db_session
from portfoliomaster.db.schema import Base, MarketQuote, UserInstrument


TEST_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"


def bearer(secret=TEST_SECRET):
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": "authenticated",
            "role": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_health_responds_while_backup_restore_is_waiting(monkeypatch, tenant_engine):
    restoring = threading.Event()
    release_restore = threading.Event()
    restore_finished = threading.Event()

    def slow_restore(payload):
        restoring.set()
        release_restore.wait(timeout=2)
        restore_finished.set()
        return {"status": "ok"}

    monkeypatch.setattr(backup, "is_multi_tenant_db", lambda: False)
    monkeypatch.setattr(backup, "restore_from_json", slow_restore)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/health")).status_code == 200
            restore = asyncio.create_task(client.post(
                "/api/backup/restore",
                headers=bearer(),
                files={"file": ("backup.json", b'{"version":"1.0","instruments":[]}', "application/json")},
            ))
            try:
                assert await asyncio.to_thread(restoring.wait, 3)
                assert (await client.get("/health")).status_code == 200
                assert not restore_finished.is_set()
            finally:
                release_restore.set()
                assert (await restore).status_code == 200

    asyncio.run(probe())


@pytest.fixture
def tenant_engine(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'tenant.db'}"
    engine = create_engine(url, pool_size=1, max_overflow=0)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
    monkeypatch.setattr(db_session, "_ENGINE", engine)
    monkeypatch.setattr(db_session, "_SESSION_FACTORY", None)
    try:
        yield engine
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("manual_price", [None, 19.25])
def test_instrument_lookup_does_not_hold_a_database_connection(monkeypatch, tenant_engine, manual_price):
    observed = []

    def company_name(symbol):
        observed.append(("name", tenant_engine.pool.checkedout()))
        return "Example Company"

    class Yahoo:
        def fetch(self, symbols):
            observed.append(("quote", tenant_engine.pool.checkedout()))
            return {symbols[0]: Quote(price=Decimal("20.50"), status=QuoteStatus.FRESH)}

    def year_start(symbol):
        observed.append(("ytd", tenant_engine.pool.checkedout()))
        return 15.0, date(2025, 1, 2)

    monkeypatch.setattr(instruments, "resolve_company_name", company_name)
    monkeypatch.setattr(refresh, "_get_yahoo_adapter", Yahoo)
    monkeypatch.setattr(instruments, "_fetch_start_of_year_quote", year_start)
    client = TestClient(main.app, headers=bearer())
    response = client.post("/api/instruments", json={
        "user_ticker": "POOL", "currency": "USD", "fetch_yahoo": True, "manual_price": manual_price,
    })
    assert response.status_code == 201, response.text
    expected = [("name", 0), ("ytd", 0)] if manual_price else [("name", 0), ("quote", 0), ("ytd", 0)]
    assert observed == expected
    assert response.json()["instrument"]["start_of_year_price"] == 15.0
    assert response.json()["quote"]["price"] == (manual_price or 20.5)
    assert tenant_engine.pool.checkedout() == 0
    duplicate = client.post("/api/instruments", json={"user_ticker": "POOL", "fetch_yahoo": False})
    assert duplicate.status_code == 400
    assert tenant_engine.pool.checkedout() == 0


def test_failed_instrument_write_rolls_back_and_releases_connection(tenant_engine):
    def reject_instrument_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO user_instruments"):
            raise RuntimeError("Simulated instrument write failure")

    event.listen(tenant_engine, "before_cursor_execute", reject_instrument_insert)
    client = TestClient(main.app, base_url="https://testserver", headers=bearer(), raise_server_exceptions=False)
    response = client.post("/api/instruments", json={"user_ticker": "ROLLBACK", "fetch_yahoo": False})
    assert response.status_code == 500
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert tenant_engine.pool.checkedout() == 0
    with tenant_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(UserInstrument)) == 0
        assert conn.scalar(select(func.count()).select_from(MarketQuote)) == 0


@pytest.fixture
def startup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'startup.db'}")
    monkeypatch.setenv("ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)


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


def test_development_cannot_fall_back_to_test_credentials(monkeypatch, startup_env):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setenv("TEST_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("DEV_JWT_SECRET", TEST_SECRET)
    with pytest.raises(ValueError, match="SUPABASE_JWT_SECRET"):
        with TestClient(main.app):
            pytest.fail("Startup accepted test credentials in development")


def test_test_mode_does_not_bypass_validation_on_render(monkeypatch, startup_env):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    with pytest.raises(ValueError, match="SUPABASE_JWT_SECRET"):
        with TestClient(main.app):
            pytest.fail("Render bypassed credential validation")


def test_production_hs256_rejects_test_signature_even_without_lifespan(monkeypatch, startup_env):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    response = TestClient(main.app).get("/api/positions", headers=bearer())
    assert response.status_code == 500
    assert TEST_SECRET not in response.text


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


def test_security_headers_cover_success_error_and_cors_preflight(monkeypatch):
    client = TestClient(main.app, base_url="https://testserver")
    responses = [
        client.get("/health"),
        client.get("/api/positions"),
        client.options("/api/positions", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
        }),
    ]
    assert [response.status_code for response in responses] == [200, 401, 200]
    for response in responses:
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["strict-transport-security"] == "max-age=31536000"

    client = TestClient(main.app)
    assert "strict-transport-security" not in client.get("/health", headers={"X-Forwarded-Proto": "https"}).headers
    monkeypatch.setenv("RENDER", "true")
    assert client.get("/health").headers["strict-transport-security"] == "max-age=31536000"
