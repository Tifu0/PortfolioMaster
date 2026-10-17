from typing import List, Dict, Optional
from ..providers.base import MarketDataProvider
from ..core.models import Quote, QuoteStatus
from ..core.config import DEFAULT_BATCH_SIZE, get_batch_size
import time
import logging

class BatchRunner:
    """Executes market data refreshes in batches."""

    def __init__(self, provider: MarketDataProvider, batch_size: Optional[int] = None):
        self.provider = provider
        self.batch_size = batch_size if batch_size is not None else get_batch_size()
        self.logger = logging.getLogger(__name__)

    def run(self, symbols: List[str]) -> Dict[str, Quote]:
        """Run batch refresh with retries and error isolation."""
        results = {}
        total_symbols = len(symbols)
        if total_symbols == 0:
            return results

        total_batches = (total_symbols + self.batch_size - 1) // self.batch_size
        for batch_idx, i in enumerate(range(0, total_symbols, self.batch_size), start=1):
            chunk = symbols[i : i + self.batch_size]
            self.logger.info(
                f"[BatchRunner] Batch {batch_idx}/{total_batches} ({len(chunk)} symbols): {chunk}"
            )

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
