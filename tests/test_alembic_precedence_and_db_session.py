"""Tests for Alembic URL precedence, production fail-closed behavior, and driver connect args."""

from __future__ import annotations

import os
import importlib.util
from pathlib import Path
import pytest
from unittest.mock import patch

from alembic.config import Config
from portfoliomaster.db.session import get_database_url, get_engine

# Dynamically load the project's alembic/env.py
_env_path = Path(__file__).resolve().parent.parent / "alembic" / "env.py"
_spec = importlib.util.spec_from_file_location("project_alembic_env", _env_path)
project_alembic_env = importlib.util.module_from_spec(_spec)
# Note: env.py executes on import if not guarded or if context is imported,
# but we can test get_url directly.
_spec.loader.exec_module(project_alembic_env)


def test_env_database_url_wins_over_ini_url():
    """Alembic uses the explicit INI URL unless overridden by DATABASE_URL."""
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg2://user:password@remotehost/ini_db")
    with patch.dict(os.environ, {}, clear=True):
        assert project_alembic_env.get_url(cfg=alembic_cfg) == "postgresql+psycopg://user:password@remotehost/ini_db"

    dummy_pg_url = "postgresql://user_test:pass_test@remotehost:5432/test_db"
    with patch.dict(os.environ, {"DATABASE_URL": dummy_pg_url}):
        resolved = project_alembic_env.get_url(cfg=alembic_cfg)
        assert resolved == "postgresql+psycopg://user_test:pass_test@remotehost:5432/test_db"


def test_alembic_get_url_ignores_placeholder_driver_in_ini():
    """If alembic.ini has driver:// placeholder, get_url() falls back to get_database_url()."""
    with patch.dict(os.environ, {}, clear=True):
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", "driver://user:pass@localhost/dbname")
        resolved = project_alembic_env.get_url(cfg=alembic_cfg)
        # In non-production without DATABASE_URL, fallback is sqlite:///portfolio.db
        assert resolved.startswith("sqlite:")


def test_production_fails_closed_when_database_url_missing():
    """When ENVIRONMENT=production, missing DATABASE_URL must raise RuntimeError."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            get_database_url()
        assert "DATABASE_URL environment variable is required in production" in str(exc_info.value)
        # Ensure error does not expose any credentials
        assert "password" not in str(exc_info.value).lower()


def test_production_fails_closed_on_render_environment():
    """When RENDER=true, missing DATABASE_URL must raise RuntimeError."""
    with patch.dict(os.environ, {"RENDER": "true"}, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            get_database_url()
        assert "DATABASE_URL environment variable is required in production" in str(exc_info.value)


def test_production_fails_closed_when_database_url_is_placeholder():
    """When DATABASE_URL is placeholder, it must fail closed in production."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "DATABASE_URL": "driver://user:pass@localhost/dbname"}):
        with pytest.raises(RuntimeError) as exc_info:
            get_database_url()
        assert "DATABASE_URL environment variable is required in production" in str(exc_info.value)


def test_postgresql_aliases_use_psycopg_and_disable_prepared_statements():
    """Existing PostgreSQL URLs work with the sole installed driver."""
    target = "user:p%40ss@localhost:6543/testdb?sslmode=require"
    for scheme in ("postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"):
        engine = get_engine(db_url=f"{scheme}://{target}")
        try:
            assert engine.dialect.driver == "psycopg"
            assert engine.url.render_as_string(hide_password=False) == f"postgresql+psycopg://{target}"
            with patch.object(
                engine.dialect, "connect", side_effect=RuntimeError("connection intercepted")
            ) as connect:
                with pytest.raises(RuntimeError, match="connection intercepted"):
                    engine.connect()
                assert connect.call_args.kwargs["prepare_threshold"] is None
        finally:
            engine.dispose()


def test_postgres_url_normalization():
    """Heroku-style PostgreSQL URLs select Psycopg 3 explicitly."""
    with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@localhost:5432/db"}):
        normalized = get_database_url()
        assert normalized == "postgresql+psycopg://user:pass@localhost:5432/db"


def test_postgres_engine_pool_resiliency():
    """PostgreSQL engines must configure pool_pre_ping=True and pool_recycle=300."""
    with patch("portfoliomaster.db.session.create_engine") as mock_create:
        get_engine(db_url="postgresql+psycopg://user:pass@localhost/testdb")
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs.get("pool_pre_ping") is True
        assert kwargs.get("pool_recycle") == 300


def test_sqlite_engine_does_not_configure_pg_pool_kwargs():
    """SQLite engines do not configure pool_pre_ping or pool_recycle."""
    with patch("portfoliomaster.db.session.create_engine") as mock_create:
        get_engine(db_url="sqlite:///:memory:")
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert "pool_pre_ping" not in kwargs
        assert "pool_recycle" not in kwargs
