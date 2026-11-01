"""Unit tests for in-memory quote delta filtering and zero-read ON CONFLICT bulk upsert."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from portfoliomaster.db.schema import Base
from portfoliomaster.db.multi_tenant_repository import (
    GlobalMarketQuotesRepository,
    clear_quote_delta_cache,
    filter_unchanged_quotes,
)


@pytest.fixture
def in_memory_db():
    """In-memory SQLite database configured with multi-tenant schema."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()



def test_delta_filter_skips_unchanged_quotes():
    """Verify that filter_unchanged_quotes skips writes when quotes are identical."""
    clear_quote_delta_cache()

    quotes_first = [
        {
            "provider_symbol": "AAPL",
            "price": Decimal("230.00"),
            "previous_close": Decimal("225.00"),
            "status": "FRESH",
        },
        {
            "provider_symbol": "MSFT",
            "price": Decimal("420.00"),
            "previous_close": Decimal("415.00"),
            "status": "FRESH",
        },
    ]

    # First time: all quotes must pass through
    filtered_1 = filter_unchanged_quotes(quotes_first)
    assert len(filtered_1) == 2

    # Second time with identical data: both should be skipped (0 writes to DB!)
    filtered_2 = filter_unchanged_quotes(quotes_first)
    assert len(filtered_2) == 0

    # Third time: AAPL price changed, MSFT unchanged
    quotes_third = [
        {
            "provider_symbol": "AAPL",
            "price": Decimal("231.50"),
            "previous_close": Decimal("225.00"),
            "status": "FRESH",
        },
        {
            "provider_symbol": "MSFT",
            "price": Decimal("420.00"),
            "previous_close": Decimal("415.00"),
            "status": "FRESH",
        },
    ]
    filtered_3 = filter_unchanged_quotes(quotes_third)
    assert len(filtered_3) == 1
    assert filtered_3[0]["provider_symbol"] == "AAPL"

    # Status change (e.g. from FRESH to ERROR) must also pass through
    quotes_fourth = [
        {
            "provider_symbol": "AAPL",
            "price": Decimal("231.50"),
            "previous_close": Decimal("225.00"),
            "status": "ERROR",
            "error_message": "Rate limited",
        },
    ]
    filtered_4 = filter_unchanged_quotes(quotes_fourth)
    assert len(filtered_4) == 1
    assert filtered_4[0]["status"] == "ERROR"


def test_zero_read_bulk_upsert_preserves_valid_prices(in_memory_db):
    """Verify that upsert_market_quotes_batch correctly inserts and updates rows

    without destroying previous valid prices when temporary errors occur.
    """
    clear_quote_delta_cache()
    repo = GlobalMarketQuotesRepository(in_memory_db)

    now = datetime.now(timezone.utc)
    initial_quotes = [
        {
            "provider_symbol": "GOOGL",
            "price": Decimal("180.00"),
            "previous_close": Decimal("178.00"),
            "quote_timestamp": now,
            "status": "FRESH",
            "company_name": "Alphabet Inc.",
            "currency": "USD",
            "exchange": "NASDAQ",
        },
        {
            "provider_symbol": "AMZN",
            "price": Decimal("190.00"),
            "previous_close": Decimal("188.00"),
            "quote_timestamp": now,
            "status": "FRESH",
            "company_name": "Amazon.com Inc.",
            "currency": "USD",
            "exchange": "NASDAQ",
        },
    ]

    # Initial bulk upsert
    res = repo.upsert_market_quotes_batch(initial_quotes)
    in_memory_db.commit()
    assert len(res) == 2

    q_googl = repo.get_quote("GOOGL")
    assert q_googl is not None
    assert q_googl.price == Decimal("180.00")
    assert q_googl.company_name == "Alphabet Inc."

    # Update: GOOGL new price, AMZN temporary error (price=None, status=ERROR)
    update_quotes = [
        {
            "provider_symbol": "GOOGL",
            "price": Decimal("185.00"),
            "previous_close": Decimal("180.00"),
            "quote_timestamp": now,
            "status": "FRESH",
        },
        {
            "provider_symbol": "AMZN",
            "price": None,
            "status": "ERROR",
            "error_message": "Temporary 500 error",
        },
    ]

    res2 = repo.upsert_market_quotes_batch(update_quotes)
    in_memory_db.commit()

    q_googl_updated = repo.get_quote("GOOGL")
    assert q_googl_updated.price == Decimal("185.00")

    q_amzn_updated = repo.get_quote("AMZN")
    assert q_amzn_updated.price == Decimal("190.00")  # Preserved!
    assert q_amzn_updated.status == "ERROR"
    assert q_amzn_updated.error_message == "Temporary 500 error"
