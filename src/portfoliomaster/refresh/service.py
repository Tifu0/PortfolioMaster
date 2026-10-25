"""
Refresh Service for watchlistTracker (WT).

Orchestrates market quote refreshes for decoupled provider_symbols:
1. Queries unique provider_symbols across active instruments.
2. Enforces concurrency locking and status tracking via RefreshRun and threading locks.
3. Chunks queries into batches and fetches quotes via YahooAdapter.
4. Performs non-destructive quote upserts: preserves last valid prices and timestamps
   when Yahoo returns ERROR or UNAVAILABLE.
5. Emits progressive batch progress events for SSE and real-time streaming.
6. Auto-resolves missing historical analysis and YTD reference prices.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from ..core.config import get_batch_size
from ..core.models import Quote
from ..providers.yahoo_adapter import YahooAdapter
from .batch_runner import BatchRunner

logger = logging.getLogger(__name__)

# Global in-process concurrency lock
_refresh_lock = threading.Lock()


class RefreshService:
    """Core domain service for batch and single-symbol market data refreshes."""

    def __init__(
        self,
        provider: Optional[YahooAdapter] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        self.provider = provider or YahooAdapter()
        self.batch_size = batch_size or get_batch_size()
        self.runner = BatchRunner(provider=self.provider, batch_size=self.batch_size)

    @classmethod
    def is_locked(cls) -> bool:
        """Check if a refresh is currently running."""
        acquired = _refresh_lock.acquire(blocking=False)
        if acquired:
            _refresh_lock.release()
            return False
        return True

    def refresh_unique_symbols(
        self,
        symbols: List[str],
        on_batch_complete: Optional[Callable[[int, int, Dict[str, Quote]], None]] = None,
    ) -> Dict[str, Quote]:
        """
        Execute batch fetch for unique provider symbols.
        Deduplicates symbols so each canonical ticker is queried at most once per batch.
        """
        clean_symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s and str(s).strip()))
        if not clean_symbols:
            return {}

        logger.info(
            f"[RefreshService] Refreshing {len(clean_symbols)} unique provider symbols in batches of {self.batch_size}"
        )
        return self.runner.run(clean_symbols, on_batch_complete=on_batch_complete)

    def execute_global_refresh_uow(
        self,
        uow: Any,
        on_progress: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """
        Execute a global refresh across all tenants using the Unit of Work.
        Guarantees tenant isolation while updating globally shared market_quotes once.
        """
        acquired = _refresh_lock.acquire(blocking=False)
        if not acquired:
            return {"status": "in_progress", "detail": "A refresh is already in progress."}

        run_id = None
        try:
            # Query all distinct provider_symbols from active instruments
            from ..db.schema import UserInstrument
            from sqlalchemy import select

            stmt = select(UserInstrument.provider_symbol).where(UserInstrument.active.is_(True)).distinct()
            raw_symbols = list(uow.session.scalars(stmt).all())
            unique_symbols = [s for s in raw_symbols if s and s.strip()]
            total_symbols = len(unique_symbols)

            total_batches = (total_symbols + self.batch_size - 1) // self.batch_size if total_symbols > 0 else 0

            # Record run start in RefreshRunRepository
            run = uow.refresh_runs.start_run(total_symbols=total_symbols, trigger_type="global_worker")
            run_id = run.id
            uow.commit()

            start_evt = {
                "type": "start",
                "total_symbols": total_symbols,
                "total_batches": total_batches,
                "batch_size": self.batch_size,
            }
            if on_progress:
                on_progress(start_evt)

            updated = 0
            failed = 0
            processed = 0

            def on_batch(b_idx: int, tot_b: int, chunk_quotes: Dict[str, Quote]):
                nonlocal updated, failed, processed
                b_updated = 0
                b_failed = 0

                try:
                    for sym, q in chunk_quotes.items():
                        # Non-destructive safe upsert: preserves existing valid price if q.price is None
                        uow.quotes.upsert_market_quote_safe(
                            provider_symbol=sym,
                            price=q.price,
                            previous_close=q.previous_close,
                            quote_timestamp=q.quote_timestamp,
                            status=q.status.name if hasattr(q.status, "name") else str(q.status),
                            error_message=q.error_message,
                            provider=q.provider or "yahoo",
                        )
                        if q.is_valid():
                            updated += 1
                            b_updated += 1
                        else:
                            failed += 1
                            b_failed += 1
                        processed += 1

                    uow.commit()

                    # Update live progress in DB
                    uow.refresh_runs.update_progress(
                        run_id=run_id,
                        processed=processed,
                        successful=updated,
                        failed=failed,
                    )
                    uow.commit()
                except Exception as ex:
                    uow.rollback()
                    logger.error(f"[RefreshService] Error processing batch {b_idx}: {ex}")
                    raise

                b_evt = {
                    "type": "batch",
                    "batch_index": b_idx,
                    "total_batches": tot_b,
                    "processed_symbols": processed,
                    "total_symbols": total_symbols,
                    "updated": updated,
                    "failed": failed,
                    "batch_updated": b_updated,
                    "batch_failed": b_failed,
                }
                if on_progress:
                    on_progress(b_evt)

            self.runner.run(unique_symbols, on_batch_complete=on_batch)

            uow.refresh_runs.complete_run(
                run_id=run_id,
                status="COMPLETED",
                diagnostic_summary=f"Processed {processed} symbols: {updated} updated, {failed} failed.",
            )
            uow.commit()

            complete_evt = {
                "type": "complete",
                "status": "ok",
                "updated": updated,
                "failed": failed,
                "total": total_symbols,
            }
            if on_progress:
                on_progress(complete_evt)

            return complete_evt

        except Exception as e:
            logger.error(f"[RefreshService] Global refresh failed: {e}")
            if run_id:
                try:
                    uow.refresh_runs.complete_run(
                        run_id=run_id,
                        status="FAILED",
                        error_message=str(e),
                    )
                    uow.commit()
                except Exception:
                    pass
            err_evt = {"type": "error", "detail": str(e)}
            if on_progress:
                on_progress(err_evt)
            return {"status": "error", "detail": str(e)}

        finally:
            _refresh_lock.release()
