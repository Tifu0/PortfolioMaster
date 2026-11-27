"""Market data provider interface."""

from abc import ABC, abstractmethod
from typing import Dict, List
from ..core.models import Quote

class MarketDataProvider(ABC):
    """Contract for all market data providers."""

    @abstractmethod
    def fetch(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch quotes for a batch of symbols."""
        pass
