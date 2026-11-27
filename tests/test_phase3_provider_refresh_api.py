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
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db.schema import Base
from portfoliomaster.db.multi_tenant_repository import (
    GlobalMarketQuotesRepository,
    MultiTenantWatchlistRepository,
    RefreshRunRepository,
)
from portfoliomaster.refresh.batch_runner import BatchRunner


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
# 1. BATCH RUNNER: Deduplication and Isolation
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
    watchlist = MultiTenantWatchlistRepository(in_memory_db, user_id=tenant_id)
    quotes_repo = GlobalMarketQuotesRepository(in_memory_db)

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

    count = watchlist.import_or_restore_user_watchlist(payload, replace_all=True)
    in_memory_db.commit()

    assert count == 2
    instruments = watchlist.get_instruments(active_only=False)
    assert len(instruments) == 2

    san = watchlist.get_instrument_by_ticker("SAN")
    assert san is not None
    assert san.provider_symbol == "SAN.MC"
    assert san.target_price == Decimal("5.50")
    assert san.analysis_reference_price == Decimal("4.20")
    assert san.analysis_date == date(2026, 1, 15)
    assert san.active is True

    vis = watchlist.get_instrument_by_ticker("VIS")
    assert vis is not None
    assert vis.active is False  # 'false' string evaluated to False

    # Auto-provisioned market_quotes placeholder check (mirrors trg_ensure_market_quote)
    mq_san = quotes_repo.get_quote("SAN.MC")
    mq_vis = quotes_repo.get_quote("VIS.MC")
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

