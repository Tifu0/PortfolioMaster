from unittest.mock import MagicMock
from portfoliomaster.refresh.batch_runner import BatchRunner
from portfoliomaster.providers.base import MarketDataProvider
from portfoliomaster.core.models import Quote
from decimal import Decimal

def test_batch_runner_chunking():
    mock_provider = MagicMock(spec=MarketDataProvider)
    mock_provider.fetch.side_effect = [
        {"A": Quote(price=Decimal("10")), "B": Quote(price=Decimal("20"))},
        {"C": Quote(price=Decimal("30"))}
    ]

    runner = BatchRunner(mock_provider, batch_size=2)
    results = runner.run(["A", "B", "C"])

    assert len(results) == 3
    assert results["A"].price == Decimal("10")
    assert results["C"].price == Decimal("30")
    assert mock_provider.fetch.call_count == 2


def test_batch_runner_env_batch_size(monkeypatch):
    from portfoliomaster.core.config import get_batch_size, get_refresh_interval

    monkeypatch.setenv("REFRESH_BATCH_SIZE", "5")
    assert get_batch_size() == 5

    mock_provider = MagicMock(spec=MarketDataProvider)
    mock_provider.fetch.return_value = {
        s: Quote(price=Decimal("10")) for s in ["S1", "S2", "S3", "S4", "S5", "S6"]
    }

    runner = BatchRunner(mock_provider)
    assert runner.batch_size == 5

    runner.run(["S1", "S2", "S3", "S4", "S5", "S6"])
    # 6 items in chunks of 5 -> 2 calls
    assert mock_provider.fetch.call_count == 2


def test_refresh_interval_env(monkeypatch):
    from portfoliomaster.core.config import get_refresh_interval

    monkeypatch.setenv("REFRESH_INTERVAL_SECONDS", "30")
    assert get_refresh_interval() == 30.0

    monkeypatch.setenv("REFRESH_INTERVAL_SECONDS", "0")
    assert get_refresh_interval() == 0.0

    monkeypatch.delenv("REFRESH_INTERVAL_SECONDS", raising=False)
    # Default is 300.0
    assert get_refresh_interval() == 300.0


def test_batch_runner_on_batch_complete_callback():
    mock_provider = MagicMock(spec=MarketDataProvider)
    mock_provider.fetch.side_effect = [
        {"A": Quote(price=Decimal("10")), "B": Quote(price=Decimal("20"))},
        {"C": Quote(price=Decimal("30"))},
    ]

    runner = BatchRunner(mock_provider, batch_size=2)
    completed_batches = []

    def on_batch(batch_idx, total_batches, chunk_quotes):
        completed_batches.append((batch_idx, total_batches, list(chunk_quotes.keys())))

    results = runner.run(["A", "B", "C"], on_batch_complete=on_batch)

    assert len(results) == 3
    assert len(completed_batches) == 2
    assert completed_batches[0] == (1, 2, ["A", "B"])
    assert completed_batches[1] == (2, 2, ["C"])


