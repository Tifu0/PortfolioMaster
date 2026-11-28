"""Unit tests for BatchRunner chunking, symbol deduplication, and in-memory quote delta filter."""

from decimal import Decimal
from unittest.mock import MagicMock

from portfoliomaster.core.config import get_batch_size, get_refresh_interval
from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db.multi_tenant_repository import (
    clear_quote_delta_cache,
    filter_unchanged_quotes,
)
from portfoliomaster.providers.base import MarketDataProvider
from portfoliomaster.refresh.batch_runner import BatchRunner


def test_batch_runner_chunking():
    mock_provider = MagicMock(spec=MarketDataProvider)
    mock_provider.fetch.side_effect = [
        {"A": Quote(price=Decimal("10")), "B": Quote(price=Decimal("20"))},
        {"C": Quote(price=Decimal("30"))},
    ]

    runner = BatchRunner(mock_provider, batch_size=2)
    results = runner.run(["A", "B", "C"])

    assert len(results) == 3
    assert results["A"].price == Decimal("10")
    assert results["C"].price == Decimal("30")
    assert mock_provider.fetch.call_count == 2


def test_batch_runner_env_batch_size(monkeypatch):
    monkeypatch.setenv("REFRESH_BATCH_SIZE", "5")
    assert get_batch_size() == 5

    mock_provider = MagicMock(spec=MarketDataProvider)
    mock_provider.fetch.return_value = {
        s: Quote(price=Decimal("10")) for s in ["S1", "S2", "S3", "S4", "S5", "S6"]
    }

    runner = BatchRunner(mock_provider)
    assert runner.batch_size == 5
    runner.run(["S1", "S2", "S3", "S4", "S5", "S6"])
    assert mock_provider.fetch.call_count == 2


def test_refresh_interval_env(monkeypatch):
    monkeypatch.setenv("REFRESH_INTERVAL_SECONDS", "30")
    assert get_refresh_interval() == 30.0

    monkeypatch.setenv("REFRESH_INTERVAL_SECONDS", "0")
    assert get_refresh_interval() == 0.0

    monkeypatch.delenv("REFRESH_INTERVAL_SECONDS", raising=False)
    assert get_refresh_interval() == 300.0


def test_batch_runner_on_batch_complete_callback():
    mock_provider = MagicMock(spec=MarketDataProvider)
    mock_provider.fetch.side_effect = [
        {"A": Quote(price=Decimal("10")), "B": Quote(price=Decimal("20"))},
        {"C": Quote(price=Decimal("30"))},
    ]

    runner = BatchRunner(mock_provider, batch_size=2)
    completed_batches = []
    results = runner.run(
        ["A", "B", "C"],
        on_batch_complete=lambda idx, total, chunk: completed_batches.append((idx, total, list(chunk.keys()))),
    )

    assert len(results) == 3
    assert completed_batches == [(1, 2, ["A", "B"]), (2, 2, ["C"])]


def test_batch_runner_deduplicates_symbols():
    mock_provider = MagicMock()
    mock_provider.fetch.return_value = {
        "AAPL": Quote(price=Decimal("150.00"), status=QuoteStatus.FRESH),
        "MSFT": Quote(price=Decimal("300.00"), status=QuoteStatus.FRESH),
    }

    runner = BatchRunner(provider=mock_provider, batch_size=10)
    results = runner.run(["AAPL", "AAPL", "msft", "AAPL", "MSFT"])

    assert mock_provider.fetch.call_count == 1
    assert sorted(mock_provider.fetch.call_args[0][0]) == ["AAPL", "MSFT"]
    assert len(results) == 2


def test_delta_filter_skips_unchanged_quotes():
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
    assert len(filter_unchanged_quotes(quotes_first)) == 2
    assert len(filter_unchanged_quotes(quotes_first)) == 0

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
