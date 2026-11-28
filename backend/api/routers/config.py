"""System configuration and healthcheck router for watchlistTracker (WT)."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from portfoliomaster.core.config import get_batch_size, get_refresh_interval
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.db.session import get_engine

from ..dependencies import get_system_portfolio_store
from ..services.refresh_sse import get_refresh_state_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/")
@router.head("/")
def root():
    """Healthcheck and API information endpoint for watchlistTracker (WT)."""
    return {
        "status": "ok",
        "app": "watchlistTracker API (WT)",
        "docs": "/docs",
        "version": "2.0.0",
    }


@router.get("/health")
@router.head("/health")
@router.get("/healthcheck")
@router.head("/healthcheck")
@router.get("/api/health")
@router.head("/api/health")
@router.get("/api/healthcheck")
@router.head("/api/healthcheck")
def health_check():
    """Public liveness & database readiness check without revealing credentials or emitting COMMIT."""
    try:
        engine = get_engine()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error("[Health] Database check failed: %s", e)
        return Response(
            content='{"status": "degraded", "database": "disconnected"}',
            status_code=503,
            media_type="application/json",
        )


@router.get("/api/config")
def get_config(
    store: PortfolioStore = Depends(get_system_portfolio_store),
):
    """Return runtime configuration including refresh interval, batch size, and background sync status."""
    snapshot = get_refresh_state_snapshot()
    try:
        active_run = store.get_active_refresh_run()
        if active_run is not None:
            snapshot["is_refreshing"] = active_run.get("is_refreshing", True)
            snapshot["processed_symbols"] = active_run.get("processed_symbols", 0)
            snapshot["total_symbols"] = active_run.get("total_symbols", 0)
    except Exception as ex:
        logger.debug("[Config] Could not inspect active refresh run: %s", ex)

    return {
        "status": "ok",
        "refresh_interval_seconds": get_refresh_interval(),
        "batch_size": get_batch_size(),
        "is_refreshing": snapshot.get("is_refreshing", False),
        "last_refresh_at": snapshot.get("last_refresh_at") or snapshot.get("last_refresh_time"),
        "last_refresh_result": snapshot.get("last_refresh_result") or snapshot.get("last_refresh_status"),
        "refresh_counter": snapshot.get("refresh_counter", 0),
        "current_batch": snapshot.get("current_batch", 0),
        "total_batches": snapshot.get("total_batches", 0),
        "processed_symbols": snapshot.get("processed_symbols", 0),
        "total_symbols": snapshot.get("total_symbols", 0),
    }
