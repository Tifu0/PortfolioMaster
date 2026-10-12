"""Deterministic mock provider for testing."""

from typing import Dict, List
from .base import MarketDataProvider
from ..core.models import Quote, QuoteStatus
from datetime import datetime
from decimal import Decimal

class MockProvider(MarketDataProvider):
    """A deterministic mock provider for testing."""

    def __init__(self, mock_data: Dict[str, Quote] = None):
        self.mock_data = mock_data or {}
        self.partial_failure_symbols = set()

    def fetch(self, symbols: List[str]) -> Dict[str, Quote]:
        results = {}
        for symbol in symbols:
            if symbol in self.partial_failure_symbols:
                results[symbol] = Quote(status=QuoteStatus.ERROR, error_message="Mock error")
            else:
                results[symbol] = self.mock_data.get(symbol, Quote(status=QuoteStatus.UNAVAILABLE))
        return results

    @property
    def batch_supported(self) -> bool:
        return True

    @property
    def default_batch_size(self) -> int:
        return 10
