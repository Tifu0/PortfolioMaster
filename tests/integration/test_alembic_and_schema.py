"""Integration tests for Alembic URL precedence, DB engine config, schema parity, and offline SQL."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql

from portfoliomaster.db.schema import MarketQuote, RefreshRun, UserInstrument
from portfoliomaster.db.session import get_database_url, get_engine

_ENV_PATH = Path(__file__).resolve().parents[2] / "alembic" / "env.py"
_SPEC = importlib.util.spec_from_file_location("project_alembic_env", _ENV_PATH)
project_alembic_env = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(project_alembic_env)

OFFLINE_PG_URL = "postgresql+psycopg://offline:offline@localhost:5432/offline_test"


def _run_offline_sql(fn, *args) -> str:
    buf = io.StringIO()
    cfg = Config("alembic.ini", stdout=buf)
    with patch.dict(os.environ, {"DATABASE_URL": OFFLINE_PG_URL}):
        with contextlib.redirect_stdout(buf):
            fn(cfg, *args, sql=True)
    return buf.getvalue()


def test_env_database_url_wins_over_ini_url():
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg2://user:password@remotehost/ini_db")
    with patch.dict(os.environ, {}, clear=True):
        assert project_alembic_env.get_url(cfg=alembic_cfg) == "postgresql+psycopg://user:password@remotehost/ini_db"

    dummy_pg_url = "postgresql://user_test:pass_test@remotehost:5432/test_db"
    with patch.dict(os.environ, {"DATABASE_URL": dummy_pg_url}):
        assert project_alembic_env.get_url(cfg=alembic_cfg) == "postgresql+psycopg://user_test:pass_test@remotehost:5432/test_db"


def test_alembic_get_url_ignores_placeholder_driver_in_ini():
    with patch.dict(os.environ, {}, clear=True):
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", "driver://user:pass@localhost/dbname")
        assert project_alembic_env.get_url(cfg=alembic_cfg).startswith("sqlite:")


def test_production_fails_closed_when_database_url_missing_or_placeholder():
    for env_dict in (
        {"ENVIRONMENT": "production"},
        {"RENDER": "true"},
        {"ENVIRONMENT": "production", "DATABASE_URL": "driver://user:pass@localhost/dbname"},
    ):
        with patch.dict(os.environ, env_dict, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                get_database_url()
            assert "DATABASE_URL environment variable is required in production" in str(exc_info.value)
            assert "password" not in str(exc_info.value).lower()


def test_postgresql_aliases_use_psycopg_and_disable_prepared_statements():
    target = "user:p%40ss@localhost:6543/testdb?sslmode=require"
    for scheme in ("postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"):
        engine = get_engine(db_url=f"{scheme}://{target}")
        try:
            assert engine.dialect.driver == "psycopg"
            assert engine.url.render_as_string(hide_password=False) == f"postgresql+psycopg://{target}"
            with patch.object(engine.dialect, "connect", side_effect=RuntimeError("connection intercepted")) as connect:
                with pytest.raises(RuntimeError, match="connection intercepted"):
                    engine.connect()
                assert connect.call_args.kwargs["prepare_threshold"] is None
        finally:
            engine.dispose()


def test_postgres_url_normalization_and_pool_args():
    with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@localhost:5432/db"}):
        assert get_database_url() == "postgresql+psycopg://user:pass@localhost:5432/db"

    with patch("portfoliomaster.db.session.create_engine") as mock_create:
        get_engine(db_url="postgresql+psycopg://user:pass@localhost/testdb")
        _, kwargs = mock_create.call_args
        assert kwargs.get("pool_pre_ping") is True
        assert kwargs.get("pool_recycle") == 300

    with patch("portfoliomaster.db.session.create_engine") as mock_create:
        get_engine(db_url="sqlite:///:memory:")
        _, kwargs = mock_create.call_args
        assert "pool_pre_ping" not in kwargs
        assert "pool_recycle" not in kwargs


def test_schema_numeric_precision_nullability_and_status_type():
    price_cols = [
        MarketQuote.__table__.c.price,
        MarketQuote.__table__.c.previous_close,
        UserInstrument.__table__.c.analysis_reference_price,
        UserInstrument.__table__.c.start_of_year_price,
        UserInstrument.__table__.c.target_price,
    ]
    for col in price_cols:
        assert isinstance(col.type, Numeric)
        assert col.type.precision == 20
        assert col.type.scale == 6

    assert UserInstrument.__table__.c.company_name.nullable is True
    assert UserInstrument.__table__.c.comment.nullable is True
    assert MarketQuote.__table__.c.status.type.compile(dialect=postgresql.dialect()).upper() == "VARCHAR(20)"


def test_schema_redundant_indexes_removed_and_canonical_constraints_present():
    ui_indexes = {idx.name for idx in UserInstrument.__table__.indexes}
    rr_indexes = {idx.name for idx in RefreshRun.__table__.indexes}
    mq_indexes = {idx.name for idx in MarketQuote.__table__.indexes}

    assert "ix_user_instruments_user_id" not in ui_indexes
    assert "ix_refresh_runs_user_id" not in rr_indexes
    assert "ix_refresh_runs_status" not in rr_indexes

    assert {"idx_user_instruments_user_upper_ticker", "idx_user_instruments_tenant_active"} <= ui_indexes
    assert {"idx_refresh_runs_active", "idx_refresh_runs_user_started"} <= rr_indexes
    assert {"idx_market_quotes_status_attempt", "idx_market_quotes_last_attempt"} <= mq_indexes

    mq_checks = {c.name for c in MarketQuote.__table__.constraints if getattr(c, "sqltext", None) is not None}
    ui_checks = {c.name for c in UserInstrument.__table__.constraints if getattr(c, "sqltext", None) is not None}
    rr_checks = {c.name for c in RefreshRun.__table__.constraints if getattr(c, "sqltext", None) is not None}

    assert {"chk_market_quotes_price_pos", "chk_market_quotes_prev_close_pos", "chk_market_quotes_status"} <= mq_checks
    assert {
        "chk_user_instruments_analysis_price_pos",
        "chk_user_instruments_soy_price_pos",
        "chk_user_instruments_target_price_pos",
        "chk_user_ticker_length",
    } <= ui_checks
    assert {"chk_refresh_runs_status", "chk_counts_nonneg", "chk_completed_after_start"} <= rr_checks


def test_alembic_single_head_and_offline_sql_hardening():
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    head_rev = script.get_revision(heads[0])
    assert head_rev is not None and head_rev.revision != "2a8b9c0d1e2f"
    assert head_rev.down_revision == "2a8b9c0d1e2f"

    sql_lower = _run_offline_sql(command.upgrade, "head").lower()
    for redundant in ("ix_refresh_runs_status", "ix_refresh_runs_user_id", "ix_user_instruments_user_id"):
        assert f"drop index if exists public.{redundant}" in sql_lower or f"drop index if exists {redundant}" in sql_lower

    assert "create unique index if not exists idx_user_instruments_user_upper_ticker" in sql_lower
    assert "numeric(20, 6)" in sql_lower

    drop_view_pos = sql_lower.find("drop view if exists public.user_positions_view")
    alter_price_pos = sql_lower.find("type numeric(20, 6)")
    create_view_pos = sql_lower.find("create or replace view public.user_positions_view")
    assert -1 not in (drop_view_pos, alter_price_pos, create_view_pos)
    assert drop_view_pos < alter_price_pos < create_view_pos
    assert "security_invoker = true" in sql_lower

    assert "create or replace function public.set_updated_at()" in sql_lower
    assert "create or replace function public.ensure_market_quote_placeholder()" in sql_lower
    assert "set search_path = ''" in sql_lower
    assert "trg_ensure_market_quote" in sql_lower
    assert "trg_user_instruments_updated_at" in sql_lower
    assert "trg_refresh_runs_updated_at" in sql_lower

    for tbl in ("user_instruments", "market_quotes", "refresh_runs"):
        assert f"public.{tbl} enable row level security" in sql_lower
    assert "(select auth.uid())" in sql_lower

    assert not re.search(
        r"create\s+policy\b[^;]*\bon\s+(?:public\.)?refresh_runs\b[^;]*\buser_id\s+is\s+null",
        sql_lower,
        re.DOTALL,
    )
    assert not re.search(
        r"create\s+policy\b[^;]*\bfor\s+(?:insert|update|delete|all)\b[^;]*\bon\s+(?:public\.)?refresh_runs\b[^;]*\bto\s+authenticated\b",
        sql_lower,
        re.DOTALL,
    )
    for legacy_policy in (
        "authenticated users read relevant refresh runs",
        "authenticated users insert refresh runs",
        "authenticated users update refresh runs",
    ):
        assert f'drop policy if exists "{legacy_policy}" on public.refresh_runs' in sql_lower


def test_alembic_offline_downgrade_and_sqlite_roundtrip(tmp_path):
    sql_lower = _run_offline_sql(command.downgrade, "head:2a8b9c0d1e2f").lower()
    assert "drop trigger if exists trg_ensure_market_quote" in sql_lower
    assert "drop view if exists public.user_positions_view" in sql_lower
    assert "numeric(18, 6)" in sql_lower

    db_path = tmp_path / "alembic_roundtrip.db"
    cfg = Config("alembic.ini")
    with patch.dict(os.environ, {"DATABASE_URL": f"sqlite:///{db_path}"}):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "2a8b9c0d1e2f")
        command.upgrade(cfg, "head")
