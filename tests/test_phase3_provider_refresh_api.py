"""Phase 3 verification test suite for watchlistTracker (WT).

Tests:
1. YahooAdapter and historical price resolution without false current fallbacks (Bug 2 fix).
2. BatchRunner deduplication and resilient batch processing.
3. RefreshService concurrency locking and non-destructive quote preservation (Bug 3 fix).
4. GlobalMarketQuotesRepository.upsert_market_quote_safe matching Supabase PL/pgSQL RPC.
5. MultiTenantWatchlistRepository.import_or_restore_user_watchlist matching Supabase RPC.
6. RefreshRunRepository 60-second cooldown and anti-spam check.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db.schema import Base
from portfoliomaster.db.multi_tenant_repository import (
    GlobalMarketQuotesRepository,
    RefreshRunRepository,
    UnitOfWork,
)
from portfoliomaster.providers.yahoo_adapter import YahooAdapter
from portfoliomaster.refresh.batch_runner import BatchRunner
from portfoliomaster.refresh.service import RefreshService


@pytest.fixture
def in_memory_db():
    """In-memory SQLite database configured with multi-tenant schema."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# ==============================================================================
# 1. BUG 2 FIX: Historical Quote Fallback Verification
# ==============================================================================

def test_historical_quote_does_not_falsely_fallback_for_old_dates(monkeypatch):
    """
    Verify Bug 2 fix: If target_date is in the past (> 5 days ago) and historical data
    is missing in the lookback window, fetch_historical_quote returns None and NEVER
    substitutes current fast_info / 5-day prices.
    """
    adapter = YahooAdapter()

    # Mock yf.Ticker
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()  # No data in window
    mock_fast_info = MagicMock()
    mock_fast_info.last_price = 555.55
    mock_ticker.fast_info = mock_fast_info

    monkeypatch.setattr("yfinance.Ticker", lambda symbol: mock_ticker)

    # 1. Old historical date from 2021
    old_target = date(2021, 5, 10)
    res = adapter.fetch_historical_quote("AAPL", old_target, window_days=10)
    assert res is None, "Old historical date must return None when no history exists; never fast_info!"

    # 2. Date from 20 days ago
    twenty_days_ago = date.today() - timedelta(days=20)
    res2 = adapter.fetch_historical_quote("AAPL", twenty_days_ago, window_days=10)
    assert res2 is None, "Dates > 5 days ago must return None when lookback window is empty"

    # 3. Target date is today: fast_info fallback is permissible for closed market/intraday
    today = date.today()
    res3 = adapter.fetch_historical_quote("AAPL", today, window_days=10)
    assert res3 is not None
    assert res3[0] == Decimal("555.55")
    assert res3[1] == today


def test_historical_quote_returns_observation_within_lookback_window(monkeypatch):
    """Verify that when historical data is available on or before target date, it is returned accurately."""
    adapter = YahooAdapter()

    target_dt = date(2026, 10, 18)  # Sunday
    friday_dt = pd.Timestamp("2026-10-16")
    hist_df = pd.DataFrame({"Close": [182.40]}, index=[friday_dt])

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    monkeypatch.setattr("yfinance.Ticker", lambda symbol: mock_ticker)

    res = adapter.fetch_historical_quote("AAPL", target_dt, window_days=10)
    assert res is not None
    price, actual_dt = res
    assert price == Decimal("182.4")
    assert actual_dt == date(2026, 10, 16)


# ==============================================================================
# 2. BATCH RUNNER: Deduplication and Isolation
# ==============================================================================

def test_batch_runner_deduplicates_symbols():
    """Verify that BatchRunner deduplicates duplicate symbols in the request list."""
    mock_provider = MagicMock()
    mock_provider.fetch.return_value = {
        "AAPL": Quote(price=Decimal("150.00"), status=QuoteStatus.FRESH),
        "MSFT": Quote(price=Decimal("300.00"), status=QuoteStatus.FRESH),
    }

    runner = BatchRunner(provider=mock_provider, batch_size=10)
    symbols = ["AAPL", "AAPL", "msft", "AAPL", "MSFT"]
    results = runner.run(symbols)

    # Provider fetch must have been called with deduplicated symbols ['AAPL', 'MSFT']
    assert mock_provider.fetch.call_count == 1
    call_args = mock_provider.fetch.call_args[0][0]
    assert sorted(call_args) == ["AAPL", "MSFT"]
    assert len(results) == 2


# ==============================================================================
# 3. GLOBAL QUOTES REPO: Non-Destructive Safe Upsert (Bug 3 Fix)
# ==============================================================================

def test_upsert_market_quote_safe_preserves_valid_price_on_failure(in_memory_db):
    """
    Verify that upsert_market_quote_safe preserves existing valid price and timestamp
    when incoming update is an ERROR or UNAVAILABLE (mirroring Supabase RPC).
    """
    repo = GlobalMarketQuotesRepository(in_memory_db)
    valid_ts = datetime(2026, 10, 20, 15, 30, 0, tzinfo=timezone.utc)

    # 1. Successful first fetch
    q1 = repo.upsert_market_quote_safe(
        provider_symbol="SAN.MC",
        price=Decimal("4.500000"),
        previous_close=Decimal("4.400000"),
        quote_timestamp=valid_ts,
        status="FRESH",
        exchange="BME",
        currency="EUR",
        company_name="Banco Santander",
    )
    in_memory_db.commit()

    assert q1.price == Decimal("4.500000")
    assert q1.previous_close == Decimal("4.400000")
    assert q1.status == "FRESH"
    assert q1.last_valid_fetched_at is not None

    last_valid_time = q1.last_valid_fetched_at

    # 2. Subsequent failure from Yahoo
    q2 = repo.upsert_market_quote_safe(
        provider_symbol="SAN.MC",
        price=None,
        status="ERROR",
        error_message="Yahoo HTTP 503 Service Unavailable",
    )
    in_memory_db.commit()

    # BUG 3 FIX: Must preserve previous price, prev_close, timestamp, and last_valid_fetched_at!
    assert q2.price == Decimal("4.500000"), "Price must NOT be wiped by temporary provider failure!"
    assert q2.previous_close == Decimal("4.400000")
    assert q2.last_valid_fetched_at == last_valid_time
    assert q2.status == "ERROR"
    assert q2.error_message == "Yahoo HTTP 503 Service Unavailable"
    assert q2.last_attempt_at is not None


# ==============================================================================
# 4. MULTI-TENANT REPO: import_or_restore_user_watchlist RPC Parity
# ==============================================================================

def test_import_or_restore_user_watchlist_parity(in_memory_db):
    """
    Verify import_or_restore_user_watchlist in MultiTenantWatchlistRepository
    mirrors Supabase RPC public.import_or_restore_user_watchlist.
    """
    tenant_id = uuid.uuid4()
    uow = UnitOfWork(in_memory_db, user_id=tenant_id)

    payload = [
        {
            "user_ticker": "SAN",
            "provider_symbol": "SAN.MC",
            "exchange": "BME",
            "currency": "EUR",
            "company_name": "Banco Santander",
            "target_price": "5.50",
            "analysis_date": "2026-01-15",
            "analysis_reference_price": "4.20",
            "active": True,
        },
        {
            "user_ticker": "VIS",
            "provider_symbol": "VIS.MC",
            "exchange": "BME",
            "currency": "EUR",
            "comment": "Watch closely",
            "active": "false",  # Verifies string boolean parsing fix
        },
    ]

    count = uow.watchlist.import_or_restore_user_watchlist(payload, replace_all=True)
    uow.commit()

    assert count == 2
    instruments = uow.watchlist.get_instruments(active_only=False)
    assert len(instruments) == 2

    san = uow.watchlist.get_instrument_by_ticker("SAN")
    assert san is not None
    assert san.provider_symbol == "SAN.MC"
    assert san.target_price == Decimal("5.50")
    assert san.analysis_reference_price == Decimal("4.20")
    assert san.analysis_date == date(2026, 1, 15)
    assert san.active is True

    vis = uow.watchlist.get_instrument_by_ticker("VIS")
    assert vis is not None
    assert vis.active is False  # 'false' string evaluated to False

    # Auto-provisioned market_quotes placeholder check (mirrors trg_ensure_market_quote)
    mq_san = uow.quotes.get_quote("SAN.MC")
    mq_vis = uow.quotes.get_quote("VIS.MC")
    assert mq_san is not None
    assert mq_vis is not None
    assert mq_san.provider_symbol == "SAN.MC"


# ==============================================================================
# 5. REFRESH RUN REPO: Cooldown & Concurrency
# ==============================================================================

def test_refresh_run_cooldown_and_concurrency(in_memory_db):
    """
    Verify 60-second anti-spam cooldown and active run concurrency detection
    mirroring Supabase request_user_refresh().
    """
    repo = RefreshRunRepository(in_memory_db)
    user_id = uuid.uuid4()

    # Initial check: user can refresh
    can_rf, err = repo.can_user_refresh(user_id=user_id, cooldown_seconds=60)
    assert can_rf is True
    assert err is None

    # Start a run
    run = repo.start_run(total_symbols=10, trigger_type="user", user_id=user_id)
    in_memory_db.commit()

    # Check: running execution blocks concurrent request
    can_rf_blocked, err_blocked = repo.can_user_refresh(user_id=user_id, cooldown_seconds=60)
    assert can_rf_blocked is False
    assert "already have a refresh in progress" in err_blocked

    # Complete the run
    repo.complete_run(run_id=run.id, status="COMPLETED")
    in_memory_db.commit()

    # Check: completed run triggers cooldown
    can_rf_cooldown, err_cooldown = repo.can_user_refresh(user_id=user_id, cooldown_seconds=60)
    assert can_rf_cooldown is False
    assert "Please wait" in err_cooldown


# ==============================================================================
# 6. REFRESH SERVICE: Global Decoupled Refresh & Non-Destructive Update
# ==============================================================================

def test_refresh_service_global_refresh_flow(in_memory_db):
    """
    Verify that RefreshService refreshes decoupled unique provider_symbols once
    and safely updates market quotes across all active tenant instruments.
    """
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    uow_a = UnitOfWork(in_memory_db, user_id=tenant_a)
    uow_b = UnitOfWork(in_memory_db, user_id=tenant_b)

    # Both users watch AAPL
    uow_a.watchlist.create_instrument(user_ticker="AAPL", provider_symbol="AAPL")
    uow_b.watchlist.create_instrument(user_ticker="APPLE", provider_symbol="AAPL")
    in_memory_db.commit()

    # Mock provider returning a fresh quote for AAPL
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = {
        "AAPL": Quote(
            price=Decimal("230.50"),
            previous_close=Decimal("228.00"),
            quote_timestamp=datetime.now(timezone.utc),
            status=QuoteStatus.FRESH,
            provider="YahooMock",
        )
    }

    service = RefreshService(provider=mock_adapter, batch_size=10)
    uow_global = UnitOfWork(in_memory_db)
    res = service.execute_global_refresh_uow(uow_global)

    assert res["status"] == "ok"
    assert res["updated"] == 1
    assert res["total"] == 1  # 1 unique provider symbol, even though 2 tenant instruments watch it

    # Check market quote was updated
    quote = uow_global.quotes.get_quote("AAPL")
    assert quote is not None
    assert quote.price == Decimal("230.50")
    assert quote.status == "FRESH"


def test_upsert_market_quotes_batch(in_memory_db):
    """Verify that upsert_market_quotes_batch performs fast non-destructive bulk upserts."""
    repo = GlobalMarketQuotesRepository(in_memory_db)

    # 1. Bulk insert
    payload = [
        {
            "provider_symbol": "AAPL",
            "price": Decimal("230.50"),
            "previous_close": Decimal("228.00"),
            "quote_timestamp": datetime.now(timezone.utc),
            "status": "FRESH",
            "company_name": "Apple Inc.",
        },
        {
            "provider_symbol": "MSFT",
            "price": Decimal("450.00"),
            "previous_close": Decimal("445.00"),
            "quote_timestamp": datetime.now(timezone.utc),
            "status": "FRESH",
            "company_name": "Microsoft Corp.",
        },
    ]
    quotes = repo.upsert_market_quotes_batch(payload)
    in_memory_db.commit()

    assert len(quotes) == 2
    q_aapl = repo.get_quote("AAPL")
    assert q_aapl is not None
    assert q_aapl.price == Decimal("230.50")
    assert q_aapl.company_name == "Apple Inc."

    # 2. Bulk update with 1 success and 1 error (non-destructive)
    update_payload = [
        {
            "provider_symbol": "AAPL",
            "price": Decimal("235.00"),
            "previous_close": Decimal("230.50"),
            "status": "FRESH",
        },
        {
            "provider_symbol": "MSFT",
            "price": None,
            "status": "ERROR",
            "error_message": "Rate limited",
        },
    ]
    repo.upsert_market_quotes_batch(update_payload)
    in_memory_db.commit()

    q_aapl_updated = repo.get_quote("AAPL")
    assert q_aapl_updated.price == Decimal("235.00")

    q_msft_updated = repo.get_quote("MSFT")
    # MSFT existing price (450.00) MUST be preserved on error!
    assert q_msft_updated.price == Decimal("450.00")
    assert q_msft_updated.status == "ERROR"
    assert q_msft_updated.error_message == "Rate limited"

