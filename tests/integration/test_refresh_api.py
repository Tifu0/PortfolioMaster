"""Integration tests for refresh cooldowns, SSE revision sync, and RefreshRun coordination."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.api.dependencies import get_yahoo_provider
from backend.api.main import app
from backend.api.routers import refresh
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db.connection import get_connection
from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository
from portfoliomaster.db.repository import get_all_instruments, upsert_instrument, upsert_quote
from portfoliomaster.db.schema import Base, RefreshRun
from portfoliomaster.providers.mock_provider import MockProvider
from portfoliomaster.providers.yahoo_adapter import YahooAdapter
from portfoliomaster.refresh.batch_runner import BatchRunner


def test_consecutive_refresh_calls_trigger_cooldown(sqlite_api_client):
    upsert_instrument(Instrument(user_ticker="SAN.MC", provider_symbol="SAN.MC", exchange=Exchange.SPAIN, currency="EUR", company_name="Banco Santander", active=True))
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"SAN.MC": Quote(price=Decimal("4.50"), previous_close=Decimal("4.40"), status=QuoteStatus.FRESH, provider="yahoo_mock")}
    app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter

    res1 = sqlite_api_client.post("/api/refresh")
    assert res1.status_code == 200 and res1.json()["status"] == "ok" and res1.json()["updated"] >= 1
    assert mock_adapter.fetch.call_count == 1

    res2 = sqlite_api_client.post("/api/refresh")
    assert res2.status_code == 200 and res2.json()["status"] == "fresh" and res2.json()["refreshed_count"] == 0
    assert mock_adapter.fetch.call_count == 1


def test_single_instrument_cooldown_and_force_bypass(sqlite_api_client):
    upsert_instrument(Instrument(user_ticker="IBE.MC", provider_symbol="IBE.MC", exchange=Exchange.SPAIN, currency="EUR", company_name="Iberdrola", active=True))
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"IBE.MC": Quote(price=Decimal("12.20"), previous_close=Decimal("12.00"), status=QuoteStatus.FRESH, provider="yahoo_mock")}
    app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter

    r1 = sqlite_api_client.post("/api/instruments/IBE.MC/refresh")
    assert r1.status_code == 200 and r1.json()["status"] == "ok" and r1.json()["price"] == 12.20
    assert mock_adapter.fetch.call_count == 1

    r2 = sqlite_api_client.post("/api/instruments/IBE.MC/refresh")
    assert r2.status_code == 200 and r2.json()["status"] == "fresh" and r2.json()["refreshed_count"] == 0
    assert mock_adapter.fetch.call_count == 1

    r3 = sqlite_api_client.post("/api/instruments/IBE.MC/refresh?force=true")
    assert r3.status_code == 200 and r3.json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 2


def test_refresh_all_force_bypasses_cooldown(sqlite_api_client):
    upsert_instrument(Instrument(user_ticker="TEF.MC", provider_symbol="TEF.MC", exchange=Exchange.SPAIN, currency="EUR", company_name="Telefonica", active=True))
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {"TEF.MC": Quote(price=Decimal("3.80"), previous_close=Decimal("3.75"), status=QuoteStatus.FRESH, provider="yahoo_mock")}
    app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter

    assert sqlite_api_client.post("/api/refresh").json()["status"] == "ok"
    assert sqlite_api_client.post("/api/refresh?force=true").json()["status"] == "ok"
    assert mock_adapter.fetch.call_count == 2


def test_listening_stream_reports_revision_and_releases_subscription(monkeypatch):
    monkeypatch.setattr(refresh, "_sse_subscribers", set())
    stamp = "2026-01-02T12:00:00+00:00"
    monkeypatch.setitem(refresh._state, "last_refresh_at", stamp)
    monkeypatch.setitem(refresh._state, "refresh_counter", 5)
    monkeypatch.setitem(refresh._state, "is_refreshing", False)

    async def listen():
        response = await refresh.refresh_stream(mode="listen", user_id=uuid.uuid4())
        stream = response.body_iterator
        try:
            connection = json.loads((await anext(stream)).removeprefix("data: "))
            assert connection["type"] == "connected"
            assert connection["last_refresh_at"] == stamp
            assert connection["refresh_counter"] == 5
            refresh._broadcast_refresh_event({"type": "complete"})
            completion = json.loads((await anext(stream)).removeprefix("data: "))
            assert completion["last_refresh_at"] == stamp
            assert completion["refresh_counter"] == 5
        finally:
            await stream.aclose()
            assert refresh._get_active_sse_subscribers_count() == 0

    asyncio.run(listen())


def test_multi_instance_refresh_coordination_and_stale_timeout():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    try:
        with Session() as session:
            repo = RefreshRunRepository(session)
            repo.start_run(total_symbols=5, trigger_type="batch_worker")
            session.commit()
            assert repo.is_running(scope="GLOBAL") is True

        now_utc = datetime.now(timezone.utc)
        with Session() as session:
            stale = RefreshRun(trigger_type="batch_worker", status="RUNNING", total_symbols=10, started_at=now_utc - timedelta(minutes=11))
            session.add(stale)
            session.commit()

            cutoff = now_utc - timedelta(minutes=10)
            for sr in session.scalars(select(RefreshRun).where(RefreshRun.status == "RUNNING", RefreshRun.started_at < cutoff)).all():
                sr.status = "TIMEOUT"
                sr.diagnostic_summary = "Timed out after 10 minutes without completion."
            session.commit()

            assert session.get(RefreshRun, stale.id).status == "TIMEOUT"
    finally:
        engine.dispose()


def test_broadcast_payload_does_not_leak_private_data():
    async def _run():
        test_sub = refresh._SSESubscriber(
            queue=asyncio.Queue(maxsize=100),
            loop=asyncio.get_running_loop(),
            user_id=uuid.uuid4(),
        )
        with refresh._sse_lock:
            refresh._sse_subscribers.add(test_sub)
        try:
            refresh._broadcast_refresh_event({
                "type": "batch",
                "batch_index": 1,
                "total_batches": 2,
                "processed_symbols": 10,
                "total_symbols": 20,
                "updated": 9,
                "failed": 1,
                "batch_updated": 9,
                "batch_failed": 1,
            })
            await asyncio.sleep(0)
            received = test_sub.queue.get_nowait()
            assert "user_id" not in received and "ticker" not in received and "positions" not in received
            assert received["total_symbols"] == 20 and received["updated"] == 9
        finally:
            with refresh._sse_lock:
                refresh._sse_subscribers.discard(test_sub)

    asyncio.run(_run())


def test_refresh_functionality_with_mock_data():
    upsert_instrument(Instrument(user_ticker="AAPL", provider_symbol="AAPL", exchange=Exchange.US))
    provider = MockProvider(mock_data={"AAPL": Quote(price=Decimal("150.00"), status=QuoteStatus.FRESH)})
    runner = BatchRunner(provider=provider, batch_size=10)

    instruments = get_all_instruments()
    quotes = runner.run([inst.provider_symbol for inst in instruments if inst.provider_symbol])
    instrument_map = {inst.provider_symbol: inst.id for inst in instruments}
    for symbol, quote in quotes.items():
        quote.instrument_id = instrument_map.get(symbol)
        if quote.instrument_id:
            upsert_quote(quote)

    conn = get_connection()
    try:
        price = conn.execute("SELECT price FROM quotes WHERE instrument_id = ?", (instrument_map["AAPL"],)).fetchone()[0]
    finally:
        conn.close()
    assert Decimal(str(price)) == Decimal("150.00")


@pytest.mark.network
def test_refresh_with_yfinance_network():
    upsert_instrument(Instrument(user_ticker="AAPL", provider_symbol="AAPL", exchange=Exchange.US))
    provider = YahooAdapter()
    runner = BatchRunner(provider=provider, batch_size=10)
    instruments = get_all_instruments()
    quotes = runner.run([inst.provider_symbol for inst in instruments if inst.provider_symbol])
    assert "AAPL" in quotes and quotes["AAPL"].price is not None


def test_batch_refresh_sse_delta_and_positions_include_earnings_date(sqlite_api_client):
    """SSE batch delta and /api/positions propagate earnings_date without requiring page reload."""
    sqlite_api_client.post(
        "/api/instruments",
        json={"user_ticker": "AAPL", "currency": "USD", "fetch_yahoo": False},
    )
    sqlite_api_client.post(
        "/api/instruments",
        json={"user_ticker": "SPY", "currency": "USD", "fetch_yahoo": False},
    )

    from datetime import date

    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {
        "AAPL": Quote(
            price=Decimal("225.00"),
            previous_close=Decimal("220.00"),
            status=QuoteStatus.FRESH,
            provider="Yahoo",
            earnings_date=date(2027, 2, 4),
        ),
        "SPY": Quote(
            price=Decimal("600.00"),
            previous_close=Decimal("598.00"),
            status=QuoteStatus.FRESH,
            provider="Yahoo",
            earnings_date=None,
        ),
    }
    app.dependency_overrides[get_yahoo_provider] = lambda: mock_adapter

    events: list[dict] = []
    res = refresh._execute_refresh_all(
        on_batch_progress=events.append,
        force=True,
        provider=mock_adapter,
    )
    assert res["status"] == "ok"
    batch_events = [e for e in events if e.get("type") == "batch"]
    assert len(batch_events) == 1
    quotes_delta = batch_events[0]["quotes"]
    assert quotes_delta["AAPL"]["earnings_date"] == "2027-02-04"
    assert quotes_delta["SPY"]["earnings_date"] is None

    positions = {
        p["user_ticker"]: p
        for p in sqlite_api_client.get("/api/positions").json()["positions"]
    }
    assert positions["AAPL"]["earnings_date"] == "2027-02-04"
    assert positions["SPY"]["earnings_date"] is None
