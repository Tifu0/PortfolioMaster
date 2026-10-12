import pytest
from unittest.mock import MagicMock
from portfoliomaster.refresh.batch_runner import BatchRunner
from portfoliomaster.providers.base import MarketDataProvider
from portfoliomaster.core.models import Quote, QuoteStatus
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
