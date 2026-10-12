from typing import List, Dict
from ..providers.base import MarketDataProvider
from ..core.models import Quote, QuoteStatus
from ..core.config import DEFAULT_BATCH_SIZE
import time
import logging

class BatchRunner:
    """Executes market data refreshes in batches."""

    def __init__(self, provider: MarketDataProvider, batch_size: int = DEFAULT_BATCH_SIZE):
        self.provider = provider
        self.batch_size = batch_size
        self.logger = logging.getLogger(__name__)

    def run(self, symbols: List[str]) -> Dict[str, Quote]:
        """Run batch refresh with retries and error isolation."""
        results = {}
        for i in range(0, len(symbols), self.batch_size):
            chunk = symbols[i : i + self.batch_size]
            self.logger.info(f"Processing batch: {chunk}")

            # Simple retry logic
            success = False
            for attempt in range(2):
                try:
                    chunk_results = self.provider.fetch(chunk)
                    results.update(chunk_results)
                    success = True
                    break
                except Exception as e:
                    self.logger.error(f"Batch failed, retrying: {e}")
                    time.sleep(1) # Simple backoff

            if not success:
                # Mark as error
                for symbol in chunk:
                    if symbol not in results:
                        results[symbol] = Quote(status=QuoteStatus.ERROR, error_message="Batch failed after retries")
        return results
