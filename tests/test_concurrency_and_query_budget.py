"""Red->Green tests for Unit 4: concurrency, session pool hygiene, SSE tenant isolation, and query budgets."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import jwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.api import main
from backend.api.routers import instruments, positions, refresh
from portfoliomaster.backup.exporters import get_export_records
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db import connection as sqlite_conn
from portfoliomaster.db import session as db_session
from portfoliomaster.db.multi_tenant_repository import (
    _LAST_KNOWN_QUOTES,
    MultiTenantWatchlistRepository,
    clear_quote_delta_cache,
)
from portfoliomaster.db.repository import upsert_instrument, upsert_quote
from portfoliomaster.db.schema import Base, MarketQuote, RefreshRun, UserInstrument
from portfoliomaster.providers.yahoo_adapter import YahooAdapter, get_resilient_session

TEST_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
TEST_SUPABASE_URL = "https://project-ref.supabase.co"


def _mint_jwt(user_id: uuid.UUID) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "role": "authenticated",
            "iss": f"{TEST_SUPABASE_URL}/auth/v1",
            "iat": now,
            "exp": now + 3600,
        },
        TEST_SECRET,
        algorithm="HS256",
    )


@contextmanager
def record_sqlalchemy_queries(engine):
    """Collect SQL statements executed against a SQLAlchemy engine."""
    queries: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield queries
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


@pytest.fixture
def isolated_mt_env(monkeypatch, tmp_path):
    """Isolated multi-tenant FastAPI TestClient environment backed by temp SQLite."""
    db_path = tmp_path / "u4_mt.db"
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
    positions.invalidate_positions_cache()
    try:
        yield engine
    finally:
        clear_quote_delta_cache()
        positions.invalidate_positions_cache()
        db_session._ENGINE = None
        db_session._SESSION_FACTORY = None
        engine.dispose()


# --------------------------------------------------------------------------- #
# 1. Query Budgets & N+1 Elimination
# --------------------------------------------------------------------------- #


def test_import_or_restore_user_watchlist_constant_query_budget(isolated_mt_env):
    """Importing or restoring N=25 instruments must execute O(1) SQL queries (<= 8)."""
    SessionLocal = sessionmaker(bind=isolated_mt_env, autoflush=False, autocommit=False)
    user_id = uuid.uuid4()
    payload = [
        {
            "user_ticker": f"TICK{i}",
            "provider_symbol": f"TICK{i}.US",
            "exchange": "NASDAQ",
            "currency": "USD",
            "company_name": f"Company {i}",
            "target_price": str(100 + i),
            "active": True,
        }
        for i in range(25)
    ]

    with SessionLocal() as session:
        repo = MultiTenantWatchlistRepository(session, user_id)
        with record_sqlalchemy_queries(isolated_mt_env) as insert_queries:
            count = repo.import_or_restore_user_watchlist(payload, replace_all=False)
            session.commit()

        assert count == 25
        assert len(insert_queries) <= 8, f"Expected <= 8 queries, got {len(insert_queries)}"

        with record_sqlalchemy_queries(isolated_mt_env) as restore_queries:
            count2 = repo.import_or_restore_user_watchlist(payload, replace_all=True)
            session.commit()

        assert count2 == 25
        assert len(restore_queries) <= 8, f"Expected <= 8 queries on restore, got {len(restore_queries)}"


def test_sqlite_get_export_records_single_query(tmp_path, monkeypatch):
    """SQLite get_export_records(N=20) must run in a single JOIN query instead of 1+N."""
    db_file = str(tmp_path / "export_budget.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
    sqlite_conn.init_db()

    for i in range(20):
        upsert_instrument(
            Instrument(
                user_ticker=f"EXP{i}",
                provider_symbol=f"EXP{i}",
                exchange=Exchange.US,
                currency="USD",
                company_name=f"Export Co {i}",
                active=True,
            ),
            db_path=db_file,
        )
        inst = sqlite_conn.get_connection(db_file)
        inst_id = inst.execute(
            "SELECT id FROM instruments WHERE user_ticker = ?", (f"EXP{i}",)
        ).fetchone()[0]
        inst.close()
        upsert_quote(
            Quote(
                instrument_id=inst_id,
                price=Decimal("50.00"),
                previous_close=Decimal("49.00"),
                status=QuoteStatus.FRESH,
                provider="yahoo",
            ),
            db_path=db_file,
        )

    executed_sql: list[str] = []
    orig_get_connection = sqlite_conn.get_connection

    def traced_connection(db_path=None):
        conn = orig_get_connection(db_path)
        conn.set_trace_callback(executed_sql.append)
        return conn

    monkeypatch.setattr("portfoliomaster.backup.exporters.get_connection", traced_connection, raising=False)
    monkeypatch.setattr("portfoliomaster.db.repository.get_connection", traced_connection)

    records = get_export_records(db_path=db_file)
    assert len(records) == 20
    select_queries = [q for q in executed_sql if q.strip().upper().startswith("SELECT")]
    assert len(select_queries) == 1, f"Expected 1 SELECT query, got {len(select_queries)}: {select_queries}"


def test_sqlite_import_confirm_single_transaction(tmp_path, monkeypatch):
    """POST /api/import/confirm in SQLite mode must persist 25 instruments in <= 2 connections."""
    db_file = str(tmp_path / "import_budget.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
    sqlite_conn.init_db()

    conn_count = 0
    orig_get_conn = sqlite_conn.get_connection

    def counting_conn(db_path=None):
        nonlocal conn_count
        conn_count += 1
        return orig_get_conn(db_path)

    monkeypatch.setattr("portfoliomaster.db.repository.get_connection", counting_conn)
    monkeypatch.setattr("backend.api.routers.import_export.create_automatic_safety_backup", lambda reason="": None)

    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})
    payload = {
        "instruments": [
            {
                "user_ticker": f"IMP{i}",
                "provider_symbol": f"IMP{i}",
                "exchange": "NASDAQ",
                "currency": "USD",
                "company_name": f"Import Co {i}",
                "active": True,
            }
            for i in range(25)
        ]
    }
    res = client.post("/api/import/confirm", json=payload)
    assert res.status_code == 200
    assert res.json()["committed"] == 25
    assert conn_count <= 2, f"Expected <= 2 SQLite connections, got {conn_count}"


def test_pg_list_instruments_uses_noload_without_quote_join(isolated_mt_env):
    """GET /api/instruments (PG) must not emit LEFT OUTER JOIN market_quotes."""
    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})
    client.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})

    with record_sqlalchemy_queries(isolated_mt_env) as queries:
        res = client.get("/api/instruments")

    assert res.status_code == 200
    assert res.json()["count"] == 1
    assert len(queries) == 1
    sql_lower = queries[0].lower()
    assert "market_quotes" not in sql_lower
    assert "join" not in sql_lower


def test_pg_delete_instrument_single_delete_returning(isolated_mt_env):
    """DELETE /api/instruments/{ticker} (PG) must execute 1 DELETE ... RETURNING statement."""
    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})
    client.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})

    with record_sqlalchemy_queries(isolated_mt_env) as queries:
        res = client.delete("/api/instruments/AAPL")

    assert res.status_code == 200
    assert len(queries) == 1, f"Expected 1 query, got {len(queries)}: {queries}"
    sql_lower = queries[0].lower()
    assert sql_lower.strip().startswith("delete")
    assert "returning" in sql_lower


def test_positions_no_iterrows_and_metrics_includes_inactive_parity(isolated_mt_env, monkeypatch, tmp_path):
    """GET /api/metrics must count inactive rows consistently and SQLite positions must avoid df.iterrows()."""
    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})

    # Seed 1 active + 1 inactive in multi-tenant mode
    SessionLocal = sessionmaker(bind=isolated_mt_env, autoflush=False, autocommit=False)
    with SessionLocal() as s:
        s.add(MarketQuote(provider_symbol="ACT1", status="FRESH", price=Decimal("100.00"), previous_close=Decimal("95.00")))
        s.add(MarketQuote(provider_symbol="INACT1", status="FRESH", price=Decimal("50.00"), previous_close=Decimal("50.00")))
        s.add(UserInstrument(user_id=user_id, user_ticker="ACT1", provider_symbol="ACT1", active=True))
        s.add(UserInstrument(user_id=user_id, user_ticker="INACT1", provider_symbol="INACT1", active=False))
        s.commit()

    positions.invalidate_positions_cache()
    res_pos = client.get("/api/positions")
    res_met = client.get("/api/metrics")
    assert res_pos.status_code == 200
    assert res_met.status_code == 200
    assert res_pos.json()["count"] == 2
    assert res_met.json()["total_positions"] == 2

    # SQLite mode must not call DataFrame.iterrows()
    monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_file = str(tmp_path / "no_iterrows.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
    sqlite_conn.init_db()
    upsert_instrument(Instrument(user_ticker="SQ1", provider_symbol="SQ1", active=True), db_path=db_file)

    def forbid_iterrows(self, *args, **kwargs):
        raise AssertionError("DataFrame.iterrows() must not be called in GET /api/positions")

    monkeypatch.setattr(pd.DataFrame, "iterrows", forbid_iterrows)
    positions.invalidate_positions_cache()
    res_sq = client.get("/api/positions")
    assert res_sq.status_code == 200
    assert res_sq.json()["count"] == 1


def test_health_endpoints_emit_no_commit(isolated_mt_env):
    """Healthcheck endpoints must run read-only SELECT 1 without emitting COMMIT."""
    commits = 0

    @event.listens_for(isolated_mt_env, "commit")
    def _on_commit(conn):
        nonlocal commits
        commits += 1

    try:
        client = TestClient(main.app)
        r1 = client.get("/health")
        r2 = client.get("/api/health")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert commits == 0, f"Health endpoints emitted {commits} COMMIT(s)"
    finally:
        event.remove(isolated_mt_env, "commit", _on_commit)


# --------------------------------------------------------------------------- #
# 2. DB Session Lifetimes Around Yahoo I/O & No Duplicate Commits
# --------------------------------------------------------------------------- #


def test_session_scope_closed_during_yahoo_fetch(isolated_mt_env, monkeypatch):
    """No DB session may remain open while Yahoo Finance network calls execute."""
    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})
    client.post(
        "/api/instruments",
        json={"user_ticker": "AAPL", "analysis_date": "2026-01-10", "fetch_yahoo": False},
    )

    open_sessions = 0
    orig_scope = db_session.session_scope

    @contextmanager
    def tracked_scope(*args, **kwargs):
        nonlocal open_sessions
        open_sessions += 1
        try:
            with orig_scope(*args, **kwargs) as s:
                yield s
        finally:
            open_sessions -= 1

    monkeypatch.setattr(db_session, "session_scope", tracked_scope)

    observed_during_yahoo: list[tuple[str, int]] = []

    def fake_hist(symbol, target_date, window_days=10):
        observed_during_yahoo.append(("hist", open_sessions))
        return (195.5, target_date)

    def fake_ytd(symbol, year=None):
        observed_during_yahoo.append(("ytd", open_sessions))
        return (190.0, datetime(2026, 1, 2, tzinfo=timezone.utc).date())

    mock_adapter = MagicMock()

    def fake_fetch(symbols):
        observed_during_yahoo.append(("quote", open_sessions))
        return {
            s: Quote(
                price=Decimal("205.00"),
                previous_close=Decimal("200.00"),
                quote_timestamp=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                provider="yahoo",
                status=QuoteStatus.FRESH,
            )
            for s in symbols
        }

    mock_adapter.fetch.side_effect = fake_fetch

    monkeypatch.setattr(instruments, "_fetch_historical_quote_and_date", fake_hist)
    monkeypatch.setattr(instruments, "_fetch_start_of_year_quote", fake_ytd)
    monkeypatch.setattr(refresh, "_get_yahoo_adapter", lambda: mock_adapter)
    monkeypatch.setattr(refresh, "_get_historical_quote_for_date", lambda s, d: 195.5)
    monkeypatch.setattr(refresh, "_get_start_of_year_quote", fake_ytd)

    r_an = client.post("/api/instruments/AAPL/fetch-analysis-price")
    assert r_an.status_code == 200
    r_ytd = client.post("/api/instruments/AAPL/fetch-ytd-price")
    assert r_ytd.status_code == 200
    r_single = client.post("/api/instruments/AAPL/refresh")
    assert r_single.status_code == 200
    r_batch = client.post("/api/refresh?force=true")
    assert r_batch.status_code == 200

    assert observed_during_yahoo
    for label, active_cnt in observed_during_yahoo:
        assert active_cnt == 0, f"session_scope() was still open ({active_cnt}) during Yahoo '{label}' call!"


def test_no_duplicate_commit_inside_session_scope(isolated_mt_env, monkeypatch):
    """Operations inside session_scope() must not emit redundant session.commit()."""
    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})
    client.post("/api/instruments", json={"user_ticker": "MSFT", "analysis_date": "2026-01-10", "fetch_yahoo": False})

    monkeypatch.setattr(instruments, "_fetch_historical_quote_and_date", lambda s, d, window_days=10: (400.0, d))
    monkeypatch.setattr(instruments, "_fetch_start_of_year_quote", lambda s, y=None: (390.0, datetime(2026, 1, 2).date()))

    commit_calls = 0
    orig_commit = Session.commit

    def counting_commit(self):
        nonlocal commit_calls
        commit_calls += 1
        return orig_commit(self)

    monkeypatch.setattr(Session, "commit", counting_commit)

    res_put = client.put("/api/instruments/MSFT", json={"comment": "updated"})
    assert res_put.status_code == 200
    # 1 session_scope -> at most 1 commit
    assert commit_calls == 1, f"PUT issued {commit_calls} commits instead of 1"

    commit_calls = 0
    res_an = client.post("/api/instruments/MSFT/fetch-analysis-price")
    assert res_an.status_code == 200
    # Read session (1 commit/close) + Write session (1 commit) = at most 2, never 3+
    assert commit_calls <= 2, f"fetch-analysis-price issued {commit_calls} commits"


# --------------------------------------------------------------------------- #
# 3. Multi-Tenant Refresh Isolation, Cooldown & UTC Timestamps
# --------------------------------------------------------------------------- #


def test_mt_refresh_force_isolates_tenant_symbols_and_delta_cache(isolated_mt_env, monkeypatch):
    """POST /api/refresh?force=true for User A must only refresh User A's symbols and preserve User B's delta cache."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    client_a = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_a)}"})
    client_b = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_b)}"})

    client_a.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})
    client_b.post("/api/instruments", json={"user_ticker": "NVDA", "fetch_yahoo": False})

    # Seed User B's symbol in _LAST_KNOWN_QUOTES
    _LAST_KNOWN_QUOTES["NVDA"] = (Decimal("130.00"), Decimal("128.00"), "FRESH")

    fetched_batches: list[list[str]] = []
    mock_adapter = MagicMock()

    def fake_fetch(symbols):
        fetched_batches.append(list(symbols))
        return {
            s: Quote(
                price=Decimal("210.00"),
                previous_close=Decimal("208.00"),
                quote_timestamp=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                provider="yahoo",
                status=QuoteStatus.FRESH,
            )
            for s in symbols
        }

    mock_adapter.fetch.side_effect = fake_fetch
    monkeypatch.setattr(refresh, "_get_yahoo_adapter", lambda: mock_adapter)

    res = client_a.post("/api/refresh?force=true")
    assert res.status_code == 200
    flat_fetched = [s for batch in fetched_batches for s in batch]
    assert flat_fetched == ["AAPL"], f"User A refresh leaked/included other symbols: {flat_fetched}"
    assert "NVDA" in _LAST_KNOWN_QUOTES, "User A force=true wiped User B's symbol from delta cache!"


def test_mt_refresh_per_user_cooldown_via_can_user_refresh(isolated_mt_env, monkeypatch):
    """User A cooldown must block User A's repeat refresh without blocking User B."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    client_a = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_a)}"})
    client_b = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_b)}"})

    client_a.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})
    client_b.post("/api/instruments", json={"user_ticker": "MSFT", "fetch_yahoo": False})

    mock_adapter = MagicMock()
    mock_adapter.fetch.side_effect = lambda syms: {
        s: Quote(
            price=Decimal("100.00"),
            previous_close=Decimal("99.00"),
            quote_timestamp=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            provider="yahoo",
            status=QuoteStatus.FRESH,
        )
        for s in syms
    }
    monkeypatch.setattr(refresh, "_get_yahoo_adapter", lambda: mock_adapter)

    r1 = client_a.post("/api/refresh")
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 1

    # Immediate second refresh by User A -> blocked by cooldown
    r2 = client_a.post("/api/refresh")
    assert r2.status_code == 200
    assert r2.json()["status"] == "fresh"
    assert r2.json()["refreshed_count"] == 0
    assert mock_adapter.fetch.call_count == 1

    # User B must NOT be blocked by User A's cooldown
    r3 = client_b.post("/api/refresh")
    assert r3.status_code == 200
    assert r3.json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 2


def test_unchanged_quote_still_updates_last_attempt_at(isolated_mt_env, monkeypatch):
    """When Yahoo returns an unchanged price (filtered by delta cache), last_attempt_at must still update."""
    user_id = uuid.uuid4()
    client = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_id)}"})
    client.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})

    mock_adapter = MagicMock()
    mock_adapter.fetch.side_effect = lambda syms: {
        s: Quote(
            price=Decimal("200.00"),
            previous_close=Decimal("198.00"),
            quote_timestamp=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            provider="yahoo",
            status=QuoteStatus.FRESH,
        )
        for s in syms
    }
    monkeypatch.setattr(refresh, "_get_yahoo_adapter", lambda: mock_adapter)

    # First refresh seeds price 200.00 and _LAST_KNOWN_QUOTES["AAPL"]
    assert client.post("/api/refresh").json()["status"] == "ok"

    # Backdate last_attempt_at to 1 hour ago so symbol looks stale again
    old_ts = datetime.now(timezone.utc) - timedelta(hours=1)
    SessionLocal = sessionmaker(bind=isolated_mt_env, autoflush=False, autocommit=False)
    with SessionLocal() as s:
        q = s.get(MarketQuote, "AAPL")
        q.last_attempt_at = old_ts
        # Clear RefreshRun history so can_user_refresh allows the second attempt
        s.query(RefreshRun).delete()
        s.commit()

    # Second refresh returns identical price 200.00 -> filtered by filter_unchanged_quotes,
    # yet last_attempt_at MUST advance beyond old_ts!
    r2 = client.post("/api/refresh")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"

    with SessionLocal() as s:
        q_after = s.get(MarketQuote, "AAPL")
        actual_ts = q_after.last_attempt_at
        if actual_ts.tzinfo is None:
            actual_ts = actual_ts.replace(tzinfo=timezone.utc)
        assert actual_ts > old_ts + timedelta(minutes=30), "last_attempt_at was NOT updated for unchanged quote!"


def test_yahoo_adapter_uses_utc_aware_timestamps(monkeypatch):
    """YahooAdapter.fetch must produce UTC-aware quote_timestamp and fetched_at."""
    adapter = YahooAdapter()
    mock_ticker = MagicMock()
    mock_ticker.fast_info = {"last_price": 150.0, "previous_close": 148.0, "last_update": 1700000000}
    mock_ticker.get_history_metadata.return_value = {"regularMarketPrice": 150.0, "chartPreviousClose": 148.0, "regularMarketTime": 1700000000}
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: mock_ticker)

    res = adapter.fetch(["AAPL"])
    q = res["AAPL"]
    assert q.fetched_at is not None and q.fetched_at.tzinfo == timezone.utc
    assert q.quote_timestamp is not None and q.quote_timestamp.tzinfo is not None


# --------------------------------------------------------------------------- #
# 4. SSE Pure-Subscriber, Tenant Filtering & Bounded asyncio.Queue
# --------------------------------------------------------------------------- #


def test_sse_pure_subscriber_tenant_isolation_and_queue_bounds(isolated_mt_env, monkeypatch):
    """GET /api/refresh/stream must not trigger refreshes, must use asyncio.Queue(100), and isolate tenants."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # Seed instruments for A and B
    SessionLocal = sessionmaker(bind=isolated_mt_env, autoflush=False, autocommit=False)
    with SessionLocal() as s:
        s.add(MarketQuote(provider_symbol="AAPL", status="UNAVAILABLE"))
        s.add(MarketQuote(provider_symbol="NVDA", status="UNAVAILABLE"))
        s.add(UserInstrument(user_id=user_a, user_ticker="AAPL", provider_symbol="AAPL", active=True))
        s.add(UserInstrument(user_id=user_b, user_ticker="NVDA", provider_symbol="NVDA", active=True))
        s.commit()

    called_execute = False

    def fail_if_triggered(*args, **kwargs):
        nonlocal called_execute
        called_execute = True
        return {"status": "ok"}

    monkeypatch.setattr(refresh, "_execute_refresh_all", fail_if_triggered)

    async def run_sse_checks():
        monkeypatch.setattr(refresh, "_sse_subscribers", set())
        resp_a = await refresh.refresh_stream(mode=None, trigger=1, user_id=user_a)
        resp_b = await refresh.refresh_stream(mode="listen", user_id=user_b)
        stream_a = resp_a.body_iterator
        stream_b = resp_b.body_iterator

        try:
            conn_a = json.loads((await anext(stream_a)).removeprefix("data: "))
            conn_b = json.loads((await anext(stream_b)).removeprefix("data: "))
            assert conn_a["type"] == "connected"
            assert conn_b["type"] == "connected"
            # Verify GET did not spawn _execute_refresh_all
            await asyncio.sleep(0.05)
            assert called_execute is False, "GET /api/refresh/stream must NOT trigger a refresh!"

            # Verify subscriber queues are bounded asyncio.Queue(maxsize=100)
            subs = list(refresh._sse_subscribers)
            assert len(subs) == 2
            for sub in subs:
                assert hasattr(sub, "queue")
                assert isinstance(sub.queue, asyncio.Queue)
                assert sub.queue.maxsize == 100

            # Broadcast event scoped to user_a -> only stream_a receives it
            refresh._broadcast_refresh_event(
                {"type": "batch", "batch_index": 1, "total_batches": 1, "quotes": {"AAPL": {"price": 200.0}}},
                target_user_id=user_a,
            )
            ev_a = json.loads((await asyncio.wait_for(anext(stream_a), timeout=1.0)).removeprefix("data: "))
            assert ev_a["type"] == "batch"
            assert "AAPL" in ev_a["quotes"]

            # User B must receive only keepalive (no event from User A)
            keepalive_b = await asyncio.wait_for(anext(stream_b), timeout=2.0)
            assert keepalive_b.startswith(": keepalive")

            # Overflow queue past maxsize=100 without raising or blocking
            for idx in range(120):
                refresh._broadcast_refresh_event(
                    {"type": "batch", "batch_index": idx},
                    target_user_id=user_a,
                )
            await asyncio.sleep(0.02)
        finally:
            await stream_a.aclose()
            await stream_b.aclose()
            assert refresh._get_active_sse_subscribers_count() == 0

    asyncio.run(run_sse_checks())


# --------------------------------------------------------------------------- #
# 5. Thread-Safety & Bounded Positions Cache
# --------------------------------------------------------------------------- #


def test_yahoo_adapter_resilient_session_isolated_per_thread():
    """get_resilient_session() must return thread-local requests.Session instances."""
    import threading

    barrier = threading.Barrier(2)

    def _get_in_concurrent_thread():
        barrier.wait(timeout=2)
        return get_resilient_session()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_get_in_concurrent_thread)
        f2 = pool.submit(_get_in_concurrent_thread)
        s1 = f1.result()
        s2 = f2.result()
    assert s1 is not s2, "Worker threads shared the exact same requests.Session instance!"


def test_positions_cache_bounded_maxsize(isolated_mt_env):
    """_POSITIONS_CACHE must stay bounded at maxsize=256 even when 300 distinct users query."""
    positions.invalidate_positions_cache()
    client = TestClient(main.app)
    for _ in range(300):
        uid = uuid.uuid4()
        r = client.get("/api/positions", headers={"Authorization": f"Bearer {_mint_jwt(uid)}"})
        assert r.status_code == 200
    assert len(positions._POSITIONS_CACHE) <= 256, (
        f"_POSITIONS_CACHE grew unbounded to {len(positions._POSITIONS_CACHE)}"
    )
