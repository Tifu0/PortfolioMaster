from portfoliomaster.providers.mock_provider import MockProvider
from portfoliomaster.core.models import Quote, QuoteStatus
from decimal import Decimal

def test_mock_provider_batch():
    mock_data = {
        "AAPL": Quote(price=Decimal("150.00"), status=QuoteStatus.FRESH),
        "GOOG": Quote(price=Decimal("2800.00"), status=QuoteStatus.FRESH),
    }
    provider = MockProvider(mock_data=mock_data)

    symbols = ["AAPL", "GOOG", "UNKNOWN"]
    results = provider.fetch(symbols)

    assert len(results) == 3
    assert results["AAPL"].price == Decimal("150.00")
    assert results["GOOG"].price == Decimal("2800.00")
    assert results["UNKNOWN"].status == QuoteStatus.UNAVAILABLE

def test_mock_provider_partial_failure():
    provider = MockProvider()
    provider.partial_failure_symbols.add("BAD")

    results = provider.fetch(["BAD", "GOOD"])
    assert results["BAD"].status == QuoteStatus.ERROR
    assert results["GOOD"].status == QuoteStatus.UNAVAILABLE
