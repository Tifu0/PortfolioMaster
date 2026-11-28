"""Integration tests for query budgets, DB session hygiene, connection pooling, and SSE isolation."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.api import main
from backend.api.dependencies import get_portfolio_store, get_yahoo_provider
from backend.api.main import app
from backend.api.routers import backup, instruments, positions, refresh
from portfoliomaster.backup.exporters import get_export_records
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db import connection as sqlite_conn
from portfoliomaster.db import session as db_session
from portfoliomaster.db.multi_tenant_repository import (
    _LAST_KNOWN_QUOTES,
    MultiTenantWatchlistRepository,
)
from portfoliomaster.db.repository import SqliteWatchlistStore, upsert_instrument, upsert_quote
from portfoliomaster.db.schema import Base, MarketQuote, RefreshRun, UserInstrument
from tests.conftest import mint_jwt


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
def tenant_pool_engine(monkeypatch, tmp_path):
    """Single-connection pool engine verifying zero checked-out leaks after requests."""
    url = f"sqlite:///{tmp_path / 'tenant_pool.db'}"
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
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_import_or_restore_user_watchlist_constant_query_budget(isolated_mt_env):
    """Importing or restoring N=25 instruments executes O(1) SQL queries (<= 8)."""
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
        assert count == 25 and len(insert_queries) <= 8

        with record_sqlalchemy_queries(isolated_mt_env) as restore_queries:
            count2 = repo.import_or_restore_user_watchlist(payload, replace_all=True)
            session.commit()
        assert count2 == 25 and len(restore_queries) <= 8


def test_sqlite_get_export_records_single_query(tmp_path, monkeypatch):
    """SQLite get_export_records(N=20) runs in a single JOIN query instead of 1+N."""
    db_file = str(tmp_path / "export_budget.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
    sqlite_conn.init_db()

    for i in range(20):
        upsert_instrument(
            Instrument(user_ticker=f"EXP{i}", provider_symbol=f"EXP{i}", exchange=Exchange.US, currency="USD", company_name=f"Export Co {i}", active=True),
            db_path=db_file,
        )
        conn = sqlite_conn.get_connection(db_file)
        inst_id = conn.execute("SELECT id FROM instruments WHERE user_ticker = ?", (f"EXP{i}",)).fetchone()[0]
        conn.close()
        upsert_quote(Quote(instrument_id=inst_id, price=Decimal("50.00"), previous_close=Decimal("49.00"), status=QuoteStatus.FRESH, provider="yahoo"), db_path=db_file)

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
    assert len(select_queries) == 1


def test_sqlite_import_confirm_single_transaction(sqlite_api_client, monkeypatch):
    """POST /api/import/confirm in SQLite mode persists 25 instruments in <= 2 connections."""
    conn_count = 0
    orig_get_conn = sqlite_conn.get_connection

    def counting_conn(db_path=None):
        nonlocal conn_count
        conn_count += 1
        return orig_get_conn(db_path)

    monkeypatch.setattr("portfoliomaster.db.repository.get_connection", counting_conn)
    monkeypatch.setattr("backend.api.routers.import_export.create_automatic_safety_backup", lambda reason="": None)

    payload = {
        "instruments": [
            {"user_ticker": f"IMP{i}", "provider_symbol": f"IMP{i}", "exchange": "NASDAQ", "currency": "USD", "company_name": f"Import Co {i}", "active": True}
            for i in range(25)
        ]
    }
    res = sqlite_api_client.post("/api/import/confirm", json=payload)
    assert res.status_code == 200 and res.json()["committed"] == 25
    assert conn_count <= 2


def test_pg_list_instruments_noload_and_single_delete_returning(isolated_mt_env):
    """GET /api/instruments uses noload and DELETE uses single DELETE ... RETURNING."""
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    client.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})

    with record_sqlalchemy_queries(isolated_mt_env) as list_queries:
        res = client.get("/api/instruments")
    assert res.status_code == 200 and res.json()["count"] == 1 and len(list_queries) == 1
    assert "market_quotes" not in list_queries[0].lower() and "join" not in list_queries[0].lower()

    with record_sqlalchemy_queries(isolated_mt_env) as del_queries:
        res_del = client.delete("/api/instruments/AAPL")
    assert res_del.status_code == 200 and len(del_queries) == 1
    assert del_queries[0].lower().strip().startswith("delete") and "returning" in del_queries[0].lower()


def test_positions_no_iterrows_and_metrics_includes_inactive_parity(isolated_mt_env, monkeypatch, tmp_path):
    user_id = uuid.uuid4()
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(user_id, include_iss=True)}"})
    SessionLocal = sessionmaker(bind=isolated_mt_env, autoflush=False, autocommit=False)
    with SessionLocal() as s:
        s.add(MarketQuote(provider_symbol="ACT1", status="FRESH", price=Decimal("100.00"), previous_close=Decimal("95.00")))
        s.add(MarketQuote(provider_symbol="INACT1", status="FRESH", price=Decimal("50.00"), previous_close=Decimal("50.00")))
        s.add(UserInstrument(user_id=user_id, user_ticker="ACT1", provider_symbol="ACT1", active=True))
        s.add(UserInstrument(user_id=user_id, user_ticker="INACT1", provider_symbol="INACT1", active=False))
        s.commit()

    positions.invalidate_positions_cache()
    assert client.get("/api/positions").json()["count"] == 2
    assert client.get("/api/metrics").json()["total_positions"] == 2

    monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_file = str(tmp_path / "no_iterrows.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
    sqlite_conn.init_db()
    upsert_instrument(Instrument(user_ticker="SQ1", provider_symbol="SQ1", active=True), db_path=db_file)
    monkeypatch.setattr(pd.DataFrame, "iterrows", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("iterrows forbidden")))
    positions.invalidate_positions_cache()
    res_sq = client.get("/api/positions")
    assert res_sq.status_code == 200 and res_sq.json()["count"] == 1


def test_health_endpoints_emit_no_commit(isolated_mt_env):
    commits = 0

    @event.listens_for(isolated_mt_env, "commit")
    def _on_commit(conn):
        nonlocal commits
        commits += 1

    try:
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert commits == 0
    finally:
        event.remove(isolated_mt_env, "commit", _on_commit)


def test_session_scope_closed_during_yahoo_fetch(isolated_mt_env, monkeypatch):
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    client.post("/api/instruments", json={"user_ticker": "AAPL", "analysis_date": "2026-01-10", "fetch_yahoo": False})

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
    observed: list[tuple[str, int]] = []

    def fake_hist(symbol, target_date, window_days=10):
        observed.append(("hist", open_sessions))
        return (195.5, target_date)

    def fake_ytd(symbol, year=None):
        observed.append(("ytd", open_sessions))
        return (190.0, datetime(2026, 1, 2, tzinfo=timezone.utc).date())

    mock_adapter = MagicMock()
    mock_adapter.fetch.side_effect = lambda syms: (
        observed.append(("quote", open_sessions))
        or {s: Quote(price=Decimal("205.00"), previous_close=Decimal("200.00"), quote_timestamp=datetime.now(timezone.utc), fetched_at=datetime.now(timezone.utc), provider="yahoo", status=QuoteStatus.FRESH) for s in syms}
    )

    monkeypatch.setattr(instruments, "_fetch_historical_quote_and_date", fake_hist)
    monkeypatch.setattr(instruments, "_fetch_start_of_year_quote", fake_ytd)
    monkeypatch.setattr(refresh, "_get_yahoo_adapter", lambda: mock_adapter)
    monkeypatch.setitem(app.dependency_overrides, get_yahoo_provider, lambda: mock_adapter)
    monkeypatch.setattr(refresh, "_get_historical_quote_for_date", lambda s, d: 195.5)
    monkeypatch.setattr(refresh, "_get_start_of_year_quote", fake_ytd)

    assert client.post("/api/instruments/AAPL/fetch-analysis-price").status_code == 200
    assert client.post("/api/instruments/AAPL/fetch-ytd-price").status_code == 200
    assert client.post("/api/instruments/AAPL/refresh?force=true").status_code == 200
    assert client.post("/api/refresh?force=true").status_code == 200
    assert observed and all(cnt == 0 for _, cnt in observed)


def test_no_duplicate_commit_inside_session_scope(isolated_mt_env, monkeypatch):
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
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
    assert client.put("/api/instruments/MSFT", json={"comment": "updated"}).status_code == 200
    assert commit_calls == 1

    commit_calls = 0
    assert client.post("/api/instruments/MSFT/fetch-analysis-price").status_code == 200
    assert commit_calls <= 2


def test_mt_refresh_isolation_cooldown_and_last_attempt_at(isolated_mt_env, monkeypatch):
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    client_a = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(user_a, include_iss=True)}"})
    client_b = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(user_b, include_iss=True)}"})

    client_a.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})
    client_b.post("/api/instruments", json={"user_ticker": "NVDA", "fetch_yahoo": False})
    _LAST_KNOWN_QUOTES["NVDA"] = (Decimal("130.00"), Decimal("128.00"), "FRESH")

    fetched_batches: list[list[str]] = []
    mock_adapter = MagicMock()
    mock_adapter.fetch.side_effect = lambda syms: (
        fetched_batches.append(list(syms))
        or {s: Quote(price=Decimal("210.00"), previous_close=Decimal("208.00"), quote_timestamp=datetime.now(timezone.utc), fetched_at=datetime.now(timezone.utc), provider="yahoo", status=QuoteStatus.FRESH) for s in syms}
    )
    app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter

    assert client_a.post("/api/refresh?force=true").status_code == 200
    assert [s for b in fetched_batches for s in b] == ["AAPL"]
    assert "NVDA" in _LAST_KNOWN_QUOTES

    # User A cooldown must NOT block User B
    assert client_a.post("/api/refresh").json()["status"] == "fresh"
    assert client_b.post("/api/refresh").json()["status"] == "ok"

    # Identical price still updates last_attempt_at
    old_ts = datetime.now(timezone.utc) - timedelta(hours=1)
    SessionLocal = sessionmaker(bind=isolated_mt_env, autoflush=False, autocommit=False)
    with SessionLocal() as s:
        q = s.get(MarketQuote, "AAPL")
        q.last_attempt_at = old_ts
        s.query(RefreshRun).delete()
        s.commit()

    assert client_a.post("/api/refresh").json()["status"] == "ok"
    with SessionLocal() as s:
        actual_ts = s.get(MarketQuote, "AAPL").last_attempt_at
        if actual_ts.tzinfo is None:
            actual_ts = actual_ts.replace(tzinfo=timezone.utc)
        assert actual_ts > old_ts + timedelta(minutes=30)


def test_sse_pure_subscriber_tenant_isolation_and_queue_bounds(isolated_mt_env, monkeypatch):
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
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
        stream_a, stream_b = resp_a.body_iterator, resp_b.body_iterator

        try:
            assert json.loads((await anext(stream_a)).removeprefix("data: "))["type"] == "connected"
            assert json.loads((await anext(stream_b)).removeprefix("data: "))["type"] == "connected"
            await asyncio.sleep(0.05)
            assert called_execute is False

            subs = list(refresh._sse_subscribers)
            assert len(subs) == 2 and all(isinstance(s.queue, asyncio.Queue) and s.queue.maxsize == 100 for s in subs)

            refresh._broadcast_refresh_event({"type": "batch", "batch_index": 1, "total_batches": 1, "quotes": {"AAPL": {"price": 200.0}}}, target_user_id=user_a)
            ev_a = json.loads((await asyncio.wait_for(anext(stream_a), timeout=1.0)).removeprefix("data: "))
            assert ev_a["type"] == "batch" and "AAPL" in ev_a["quotes"]
            assert (await asyncio.wait_for(anext(stream_b), timeout=2.0)).startswith(": keepalive")

            for idx in range(120):
                refresh._broadcast_refresh_event({"type": "batch", "batch_index": idx}, target_user_id=user_a)
            await asyncio.sleep(0.02)
        finally:
            await stream_a.aclose()
            await stream_b.aclose()
            assert refresh._get_active_sse_subscribers_count() == 0

    asyncio.run(run_sse_checks())


def test_positions_cache_bounded_maxsize(isolated_mt_env):
    positions.invalidate_positions_cache()
    client = TestClient(app)
    for _ in range(300):
        assert client.get("/api/positions", headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"}).status_code == 200
    assert len(positions._POSITIONS_CACHE) <= 256


def test_health_responds_while_backup_restore_is_waiting(monkeypatch, tenant_pool_engine):
    restoring, release_restore, restore_finished = threading.Event(), threading.Event(), threading.Event()

    def slow_restore(_payload):
        restoring.set()
        release_restore.wait(timeout=2)
        restore_finished.set()
        return {"status": "ok"}

    monkeypatch.setitem(main.app.dependency_overrides, get_portfolio_store, SqliteWatchlistStore)
    monkeypatch.setattr(backup, "restore_from_json", slow_restore)

    async def probe():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as client:
            assert (await client.get("/health")).status_code == 200
            task = asyncio.create_task(
                client.post(
                    "/api/backup/restore",
                    headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4())}"},
                    files={"file": ("backup.json", b'{"version":"1.0","instruments":[]}', "application/json")},
                )
            )
            try:
                assert await asyncio.to_thread(restoring.wait, 3)
                assert (await client.get("/health")).status_code == 200
                assert not restore_finished.is_set()
            finally:
                release_restore.set()
                assert (await task).status_code == 200

    asyncio.run(probe())


@pytest.mark.parametrize("manual_price", [None, 19.25])
def test_instrument_lookup_does_not_hold_a_database_connection(monkeypatch, tenant_pool_engine, manual_price):
    observed: list[tuple[str, int]] = []

    class Yahoo:
        def fetch(self, symbols):
            observed.append(("quote", tenant_pool_engine.pool.checkedout()))
            return {symbols[0]: Quote(price=Decimal("20.50"), status=QuoteStatus.FRESH)}

    monkeypatch.setattr(instruments, "resolve_company_name", lambda s: observed.append(("name", tenant_pool_engine.pool.checkedout())) or "Example Company")
    monkeypatch.setitem(main.app.dependency_overrides, get_yahoo_provider, Yahoo)
    monkeypatch.setattr(instruments, "_fetch_start_of_year_quote", lambda s: observed.append(("ytd", tenant_pool_engine.pool.checkedout())) or (15.0, date(2025, 1, 2)))

    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4())}"})
    response = client.post("/api/instruments", json={"user_ticker": "POOL", "currency": "USD", "fetch_yahoo": True, "manual_price": manual_price})
    assert response.status_code == 201
    expected = [("name", 0), ("ytd", 0)] if manual_price else [("name", 0), ("quote", 0), ("ytd", 0)]
    assert observed == expected and tenant_pool_engine.pool.checkedout() == 0
    assert client.post("/api/instruments", json={"user_ticker": "POOL", "fetch_yahoo": False}).status_code == 400


def test_failed_instrument_write_rolls_back_and_releases_connection(tenant_pool_engine):
    def reject_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO user_instruments"):
            raise RuntimeError("Simulated instrument write failure")

    event.listen(tenant_pool_engine, "before_cursor_execute", reject_insert)
    try:
        client = TestClient(app, base_url="https://testserver", headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4())}"}, raise_server_exceptions=False)
        response = client.post("/api/instruments", json={"user_ticker": "ROLLBACK", "fetch_yahoo": False})
        assert response.status_code == 500
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert tenant_pool_engine.pool.checkedout() == 0
        with tenant_pool_engine.connect() as conn:
            assert conn.scalar(select(func.count()).select_from(UserInstrument)) == 0
            assert conn.scalar(select(func.count()).select_from(MarketQuote)) == 0
    finally:
        event.remove(tenant_pool_engine, "before_cursor_execute", reject_insert)
