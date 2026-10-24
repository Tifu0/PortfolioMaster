from typing import List, Dict, Optional, Callable
from ..providers.base import MarketDataProvider
from ..core.models import Quote, QuoteStatus
from ..core.config import get_batch_size
import time
import logging

class BatchRunner:
    """Executes market data refreshes in batches."""

    def __init__(self, provider: MarketDataProvider, batch_size: Optional[int] = None):
        self.provider = provider
        self.batch_size = batch_size if batch_size is not None else get_batch_size()
        self.logger = logging.getLogger(__name__)

    def run(
        self,
        symbols: List[str],
        on_batch_complete: Optional[Callable[[int, int, Dict[str, Quote]], None]] = None,
    ) -> Dict[str, Quote]:
        """Run batch refresh with deduplication, retries, progressive callbacks, and error isolation."""
        results = {}
        # Ensure unique provider_symbols preserving order
        unique_symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s and str(s).strip()))
        total_symbols = len(unique_symbols)
        if total_symbols == 0:
            return results

        total_batches = (total_symbols + self.batch_size - 1) // self.batch_size
        for batch_idx, i in enumerate(range(0, total_symbols, self.batch_size), start=1):
            chunk = unique_symbols[i : i + self.batch_size]
            self.logger.info(
                f"[BatchRunner] Batch {batch_idx}/{total_batches} ({len(chunk)} symbols): {chunk}"
            )

            chunk_quotes: Dict[str, Quote] = {}
            # Simple retry logic
            success = False
            for attempt in range(2):
                try:
                    chunk_quotes = self.provider.fetch(chunk)
                    results.update(chunk_quotes)
                    success = True
                    break
                except Exception as e:
                    self.logger.error(f"Batch failed, retrying: {e}")
                    time.sleep(1) # Simple backoff

            if not success:
                # Mark as error
                chunk_quotes = {}
                for symbol in chunk:
                    err_quote = Quote(
                        status=QuoteStatus.ERROR,
                        error_message="Batch failed after retries",
                    )
                    chunk_quotes[symbol] = err_quote
                    if symbol not in results:
                        results[symbol] = err_quote

            # Progressive callback per batch
            if on_batch_complete:
                try:
                    on_batch_complete(batch_idx, total_batches, chunk_quotes)
                except Exception as cb_err:
                    self.logger.error(
                        f"[BatchRunner] on_batch_complete callback error: {cb_err}"
                    )

        return results
