"""Shared pytest fixtures and multi-tenant isolation helpers for PortfolioMaster."""

from __future__ import annotations

import os
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure clean test environment isolation regardless of developer .env settings
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
os.environ["SUPABASE_URL"] = ""
TEST_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
TEST_SUPABASE_URL = "https://project-ref.supabase.co"
TEST_USER_ID = uuid.UUID("c6dd2d21-c378-40f4-9848-5680db9fec27")
os.environ["SUPABASE_JWT_SECRET"] = TEST_SECRET

from backend.api import main  # noqa: E402
from backend.api.services.cache import invalidate_positions_cache  # noqa: E402
from portfoliomaster.db import connection as sqlite_conn  # noqa: E402
from portfoliomaster.db import session as db_session  # noqa: E402
from portfoliomaster.db.multi_tenant_repository import clear_quote_delta_cache  # noqa: E402
from portfoliomaster.db.schema import Base  # noqa: E402
from portfoliomaster.providers.yahoo_adapter import clear_earnings_cache  # noqa: E402


def mint_jwt(
    user_id: uuid.UUID = TEST_USER_ID,
    *,
    expires_in: int = 3600,
    secret: str = TEST_SECRET,
    aud: str = "authenticated",
    role: str | None = "authenticated",
    include_role: bool = True,
    iss: str | None = f"{TEST_SUPABASE_URL}/auth/v1",
    include_iss: bool = False,
) -> str:
    """Mint a deterministic HS256 JWT token for local API and auth boundary tests."""
    now = int(time.time())
    payload: dict[str, object] = {
        "sub": str(user_id),
        "aud": aud,
        "iat": now,
        "exp": now + expires_in,
        "email": f"user-{str(user_id)[:8]}@test.com",
    }
    if include_role and role is not None:
        payload["role"] = role
    if include_iss and iss is not None:
        payload["iss"] = iss
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def test_db_isolation(tmp_path, monkeypatch):
    """Isolate every test from developer SQLite files, global caches, and FastAPI overrides."""
    test_db_file = str(tmp_path / "test_portfolio.db")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", test_db_file)
    monkeypatch.setenv("PORTFOLIOMASTER_BACKUP_DIR", str(backup_dir))
    monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_session._ENGINE = None
    db_session._SESSION_FACTORY = None
    clear_quote_delta_cache()
    clear_earnings_cache()
    invalidate_positions_cache()
    sqlite_conn.init_db()
    yield test_db_file
    main.app.dependency_overrides.clear()
    clear_quote_delta_cache()
    clear_earnings_cache()
    invalidate_positions_cache()
    db_session._ENGINE = None
    db_session._SESSION_FACTORY = None


@pytest.fixture
def sqlite_api_client(tmp_path, monkeypatch) -> TestClient:
    """Authenticated FastAPI TestClient configured for isolated local SQLite mode."""
    db_file = tmp_path / "sqlite_api.db"
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "false")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", str(db_file))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    sqlite_conn.init_db()
    return TestClient(main.app, headers={"Authorization": f"Bearer {mint_jwt()}"})


@pytest.fixture
def isolated_mt_env(monkeypatch, tmp_path):
    """Isolated SQLite-backed multi-tenant FastAPI environment."""
    db_path = tmp_path / "mt_env.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("SUPABASE_URL", TEST_SUPABASE_URL)
    monkeypatch.setattr(db_session, "_ENGINE", engine)
    monkeypatch.setattr(db_session, "_SESSION_FACTORY", None)
    clear_quote_delta_cache()
    invalidate_positions_cache()
    try:
        yield engine
    finally:
        main.app.dependency_overrides.clear()
        clear_quote_delta_cache()
        invalidate_positions_cache()
        db_session._ENGINE = None
        db_session._SESSION_FACTORY = None
        engine.dispose()


@pytest.fixture
def in_memory_mt_session():
    """In-memory SQLAlchemy session configured with the multi-tenant schema."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
