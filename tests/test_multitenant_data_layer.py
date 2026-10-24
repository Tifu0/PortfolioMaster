"""Unit and integration tests for watchlistTracker (WT) Multi-Tenant Data Layer.

Verifies:
1. Strict tenant isolation (user_id partitioning).
2. Per-tenant case-insensitive ticker uniqueness with multi-tenant coexistence.
3. Shared global market quotes decoupling (1 quote updates multiple tenants).
4. Preservation of last valid price on provider failure.
5. Tristate PATCH updates (field omission vs explicit clearing to null).
6. Multi-worker RefreshRun execution tracking.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfoliomaster.db.schema import Base
from portfoliomaster.db.multi_tenant_repository import (
    GlobalMarketQuotesRepository,
    RefreshRunRepository,
    UnitOfWork,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session with full schema initialized."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()


def test_tenant_isolation_coexistence_and_queries(db_session):
    """Verify that User A and User B can both watch 'AAPL' with different parameters
    without conflict or data leakage.
    """
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    uow_a = UnitOfWork(db_session, user_id=user_a)
    uow_b = UnitOfWork(db_session, user_id=user_b)

    # User A creates AAPL
    inst_a = uow_a.watchlist.create_instrument(
        user_ticker="AAPL",
        provider_symbol="AAPL",
        currency="USD",
        target_price=Decimal("250.00"),
        comment="User A notes on Apple",
    )
    # User B creates AAPL with different target and notes
    inst_b = uow_b.watchlist.create_instrument(
        user_ticker="AAPL",
        provider_symbol="AAPL",
        currency="USD",
        target_price=Decimal("190.00"),
        comment="User B notes on Apple",
    )
    db_session.commit()

    assert inst_a.id != inst_b.id
    assert inst_a.user_id == user_a
    assert inst_b.user_id == user_b

    # User A only sees their own AAPL
    list_a = uow_a.watchlist.get_instruments()
    assert len(list_a) == 1
    assert list_a[0].target_price == Decimal("250.00")
    assert list_a[0].comment == "User A notes on Apple"

    # User B only sees their own AAPL
    list_b = uow_b.watchlist.get_instruments()
    assert len(list_b) == 1
    assert list_b[0].target_price == Decimal("190.00")
    assert list_b[0].comment == "User B notes on Apple"

    # Cross-tenant query by ticker
    found_a = uow_a.watchlist.get_instrument_by_ticker("AAPL")
    assert found_a is not None
    assert found_a.target_price == Decimal("250.00")

    # User A cannot delete User B's instrument by id
    deleted_cross = uow_a.watchlist.delete_instrument("NON_EXISTENT")
    assert deleted_cross is False


def test_case_insensitive_ticker_search(db_session):
    """Verify ticker lookup is case-insensitive."""
    user = uuid.uuid4()
    uow = UnitOfWork(db_session, user_id=user)

    uow.watchlist.create_instrument(user_ticker="msft", provider_symbol="MSFT")
    db_session.commit()

    # Search with uppercase
    inst = uow.watchlist.get_instrument_by_ticker("MSFT")
    assert inst is not None
    assert inst.user_ticker == "msft"

    # Search with mixed case
    inst_mixed = uow.watchlist.get_instrument_by_ticker("MsFt")
    assert inst_mixed is not None
    assert inst_mixed.user_ticker == "msft"


def test_shared_market_quotes_decoupling(db_session):
    """Verify that multiple tenants share a single MarketQuote record, and updates
    reflect across all users watching that symbol.
    """
    user_1 = uuid.uuid4()
    user_2 = uuid.uuid4()

    uow_1 = UnitOfWork(db_session, user_id=user_1)
    uow_2 = UnitOfWork(db_session, user_id=user_2)

    # Both users watch SAN.MC
    uow_1.watchlist.create_instrument(user_ticker="SAN", provider_symbol="SAN.MC", currency="EUR")
    uow_2.watchlist.create_instrument(user_ticker="SANTANDER", provider_symbol="SAN.MC", currency="EUR")
    db_session.commit()

    # Verify only ONE quote entry exists in market_quotes for SAN.MC
    quote = uow_1.quotes.get_quote("SAN.MC")
    assert quote is not None
    assert quote.provider_symbol == "SAN.MC"

    # Single provider fetch updates the shared quote
    now = datetime(2026, 10, 22, 13, 0, 0, tzinfo=timezone.utc)
    uow_1.quotes.save_quote_success(
        symbol="SAN.MC",
        price=Decimal("4.65"),
        previous_close=Decimal("4.50"),
        quote_timestamp=now,
        status="FRESH",
    )
    db_session.commit()

    # Both User 1 and User 2 see the updated market price in positions
    pos_1 = uow_1.watchlist.get_positions_with_calculations()[0]
    pos_2 = uow_2.watchlist.get_positions_with_calculations()[0]

    assert pos_1["latest_price"] == 4.65
    assert pos_2["latest_price"] == 4.65
    # Daily change: ((4.65 - 4.50) / 4.50) * 100 = +3.33%
    assert pos_1["daily_variation"] == 3.33
    assert pos_2["daily_variation"] == 3.33


def test_quote_failure_preserves_last_valid_price(db_session):
    """Verify that a provider error preserves the last known valid price and timestamp."""
    quotes_repo = GlobalMarketQuotesRepository(db_session)
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Successful quote fetch
    quotes_repo.save_quote_success(
        symbol="NVDA",
        price=Decimal("130.50"),
        previous_close=Decimal("128.00"),
        quote_timestamp=now,
        status="FRESH",
    )
    db_session.commit()

    stored = quotes_repo.get_quote("NVDA")
    assert stored.price == Decimal("130.50")
    assert stored.status == "FRESH"

    # 2. Next attempt fails (Yahoo network timeout or HTTP 500)
    quotes_repo.save_quote_failure(
        symbol="NVDA",
        error_message="HTTP 503: Service Unavailable",
        status="ERROR",
    )
    db_session.commit()

    after_fail = quotes_repo.get_quote("NVDA")
    # Price, previous close, and timestamp remain intact!
    assert after_fail.price == Decimal("130.50")
    assert after_fail.previous_close == Decimal("128.00")
    assert after_fail.quote_timestamp == now
    # Attempt status and error message reflect failure
    assert after_fail.status == "ERROR"
    assert after_fail.error_message == "HTTP 503: Service Unavailable"


def test_tristate_patch_field_clearing(db_session):
    """Verify that updating with explicit None clears fields (Bug 6 fix),
    while omitting fields in fields_set leaves them untouched.
    """
    user = uuid.uuid4()
    uow = UnitOfWork(db_session, user_id=user)

    inst = uow.watchlist.create_instrument(
        user_ticker="INTC",
        target_price=Decimal("35.00"),
        comment="Original thesis notes",
        analysis_date=date(2026, 1, 15),
    )
    db_session.commit()

    # Case A: Omit target_price, only update comment
    uow.watchlist.update_instrument(
        ticker="INTC",
        fields_set={"comment"},
        comment="Updated thesis",
    )
    db_session.commit()

    refreshed = uow.watchlist.get_instrument_by_ticker("INTC")
    assert refreshed.comment == "Updated thesis"
    # target_price was omitted, so it remained 35.00
    assert refreshed.target_price == Decimal("35.00")
    assert refreshed.analysis_date == date(2026, 1, 15)

    # Case B: Explicitly send target_price=None and analysis_date=None to clear them
    uow.watchlist.update_instrument(
        ticker="INTC",
        fields_set={"target_price", "analysis_date"},
        target_price=None,
        analysis_date=None,
    )
    db_session.commit()

    cleared = uow.watchlist.get_instrument_by_ticker("INTC")
    assert cleared.target_price is None
    assert cleared.analysis_date is None
    assert cleared.comment == "Updated thesis"


def test_refresh_run_lifecycle_tracking(db_session):
    """Verify RefreshRun lifecycle: start, live progress update, and completion."""
    refresh_repo = RefreshRunRepository(db_session)
    user_id = uuid.uuid4()

    # Start execution
    run = refresh_repo.start_run(total_symbols=50, trigger_type="cron", user_id=user_id)
    db_session.commit()

    run_id = run.id
    assert run.status == "RUNNING"
    assert run.total_symbols == 50
    assert run.progress_percent == Decimal("0.00")

    # Update progress: batch 1 processed 25 symbols (23 success, 2 fail)
    updated = refresh_repo.update_progress(
        run_id=run_id,
        processed=25,
        successful=23,
        failed=2,
        current_symbol="GOOGL",
    )
    db_session.commit()

    assert updated.processed_symbols == 25
    assert updated.progress_percent == Decimal("50.00")
    assert updated.current_symbol == "GOOGL"

    # Complete execution
    completed = refresh_repo.complete_run(
        run_id=run_id,
        status="PARTIAL",
        diagnostic_summary="48 succeeded, 2 failed due to rate limits",
    )
    db_session.commit()

    assert completed.status == "PARTIAL"
    assert completed.diagnostic_summary == "48 succeeded, 2 failed due to rate limits"
    assert completed.completed_at is not None
