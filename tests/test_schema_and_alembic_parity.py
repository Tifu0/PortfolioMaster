"""Structural parity, index hygiene, and offline Alembic SQL security tests (Unit 2)."""

from __future__ import annotations

import contextlib
import io
import os
import re
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql

from portfoliomaster.db.schema import MarketQuote, RefreshRun, UserInstrument

OFFLINE_PG_URL = "postgresql+psycopg://offline:offline@localhost:5432/offline_test"


def _run_offline_sql(fn, *args) -> str:
    """Render Alembic offline SQL against PostgreSQL dialect without touching any live DB."""
    buf = io.StringIO()
    cfg = Config("alembic.ini", stdout=buf)
    with patch.dict(os.environ, {"DATABASE_URL": OFFLINE_PG_URL}):
        with contextlib.redirect_stdout(buf):
            fn(cfg, *args, sql=True)
    return buf.getvalue()


def test_schema_numeric_precision_nullability_and_status_type():
    """Verify canonical Numeric(20, 6), nullable company_name/comment, and VARCHAR(20) status."""
    price_cols = [
        MarketQuote.__table__.c.price,
        MarketQuote.__table__.c.previous_close,
        UserInstrument.__table__.c.analysis_reference_price,
        UserInstrument.__table__.c.start_of_year_price,
        UserInstrument.__table__.c.target_price,
    ]
    for col in price_cols:
        assert isinstance(col.type, Numeric), f"{col.name} must be Numeric"
        assert col.type.precision == 20, f"{col.name} precision must be 20, got {col.type.precision}"
        assert col.type.scale == 6, f"{col.name} scale must be 6, got {col.type.scale}"

    assert UserInstrument.__table__.c.company_name.nullable is True
    assert UserInstrument.__table__.c.comment.nullable is True

    pg_status_ddl = MarketQuote.__table__.c.status.type.compile(dialect=postgresql.dialect())
    assert pg_status_ddl.upper() == "VARCHAR(20)"


def test_schema_redundant_indexes_removed_and_canonical_constraints_present():
    """Verify the 3 redundant indexes are absent and canonical constraints/functional index exist."""
    ui_indexes = {idx.name for idx in UserInstrument.__table__.indexes}
    rr_indexes = {idx.name for idx in RefreshRun.__table__.indexes}
    mq_indexes = {idx.name for idx in MarketQuote.__table__.indexes}

    assert "ix_user_instruments_user_id" not in ui_indexes
    assert "ix_refresh_runs_user_id" not in rr_indexes
    assert "ix_refresh_runs_status" not in rr_indexes

    assert "idx_user_instruments_user_upper_ticker" in ui_indexes
    assert "idx_user_instruments_tenant_active" in ui_indexes
    assert "idx_refresh_runs_active" in rr_indexes
    assert "idx_refresh_runs_user_started" in rr_indexes
    assert "idx_market_quotes_status_attempt" in mq_indexes
    assert "idx_market_quotes_last_attempt" in mq_indexes

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


def test_alembic_single_head_chained_above_2a8b9c0d1e2f():
    """Verify Alembic history has exactly 1 head chained cleanly after 2a8b9c0d1e2f."""
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    head_rev = script.get_revision(heads[0])
    assert head_rev is not None
    assert head_rev.revision != "2a8b9c0d1e2f"
    assert head_rev.down_revision == "2a8b9c0d1e2f"


def test_alembic_offline_upgrade_head_sql_contains_hardened_rls_view_triggers_and_indexes():
    """Compile full offline PostgreSQL upgrade SQL and verify U2 security and schema invariants."""
    sql = _run_offline_sql(command.upgrade, "head")
    sql_lower = sql.lower()

    # Redundant index removal + functional index creation
    for redundant in ("ix_refresh_runs_status", "ix_refresh_runs_user_id", "ix_user_instruments_user_id"):
        assert f"drop index if exists public.{redundant}" in sql_lower or f"drop index if exists {redundant}" in sql_lower

    assert "create unique index if not exists idx_user_instruments_user_upper_ticker" in sql_lower
    assert "numeric(20, 6)" in sql_lower

    # View must be dropped before ALTER COLUMN TYPE and recreated with security_invoker = true
    drop_view_pos = sql_lower.find("drop view if exists public.user_positions_view")
    alter_price_pos = sql_lower.find("type numeric(20, 6)")
    create_view_pos = sql_lower.find("create or replace view public.user_positions_view")
    assert drop_view_pos != -1
    assert alter_price_pos != -1
    assert create_view_pos != -1
    assert drop_view_pos < alter_price_pos < create_view_pos
    assert "security_invoker = true" in sql_lower

    # Trigger functions hardened with SET search_path = ''
    assert "create or replace function public.set_updated_at()" in sql_lower
    assert "create or replace function public.ensure_market_quote_placeholder()" in sql_lower
    assert "set search_path = ''" in sql_lower
    assert "trg_ensure_market_quote" in sql_lower
    assert "trg_user_instruments_updated_at" in sql_lower
    assert "trg_refresh_runs_updated_at" in sql_lower

    # RLS enabled and initPlan-optimized (select auth.uid()) used
    for tbl in ("user_instruments", "market_quotes", "refresh_runs"):
        assert f"public.{tbl} enable row level security" in sql_lower
    assert "(select auth.uid())" in sql_lower

    # Critical security check: NO policy may grant authenticated access to refresh_runs with user_id IS NULL
    assert not re.search(
        r"create\s+policy\b[^;]*\bon\s+(?:public\.)?refresh_runs\b[^;]*\buser_id\s+is\s+null",
        sql_lower,
        re.DOTALL,
    ), "refresh_runs must never expose or allow writes on user_id IS NULL via RLS policies"
    assert not re.search(
        r"create\s+policy\b[^;]*\bfor\s+(?:insert|update|delete|all)\b[^;]*\bon\s+(?:public\.)?refresh_runs\b[^;]*\bto\s+authenticated\b",
        sql_lower,
        re.DOTALL,
    ), "authenticated role must never have INSERT/UPDATE/DELETE RLS policy on refresh_runs"

    # Legacy permissive policies must be explicitly dropped for idempotency
    for legacy_policy in (
        "authenticated users read relevant refresh runs",
        "authenticated users insert refresh runs",
        "authenticated users update refresh runs",
    ):
        assert f'drop policy if exists "{legacy_policy}" on public.refresh_runs' in sql_lower


def test_alembic_offline_downgrade_to_2a8b9c0d1e2f_sql_succeeds():
    """Verify offline PostgreSQL downgrade SQL from head back to 2a8b9c0d1e2f renders cleanly."""
    sql = _run_offline_sql(command.downgrade, "head:2a8b9c0d1e2f")
    sql_lower = sql.lower()
    assert "drop trigger if exists trg_ensure_market_quote" in sql_lower
    assert "drop view if exists public.user_positions_view" in sql_lower
    assert "numeric(18, 6)" in sql_lower


def test_alembic_sqlite_upgrade_downgrade_roundtrip(tmp_path):
    """Verify Alembic upgrade head -> downgrade 2a8b9c0d1e2f -> upgrade head runs cleanly on SQLite."""
    db_path = tmp_path / "alembic_roundtrip.db"
    sqlite_url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    with patch.dict(os.environ, {"DATABASE_URL": sqlite_url}):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "2a8b9c0d1e2f")
        command.upgrade(cfg, "head")
