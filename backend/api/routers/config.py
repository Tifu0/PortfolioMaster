"""System configuration and healthcheck router for watchlistTracker (WT)."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Response

from portfoliomaster.core.config import get_batch_size, get_refresh_interval
from .refresh import _state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/")
def root():
    """Healthcheck and API information endpoint for watchlistTracker (WT)."""
    return {
        "status": "ok",
        "app": "watchlistTracker API (WT)",
        "docs": "/docs",
        "version": "2.0.0",
    }


@router.get("/health")
@router.get("/healthcheck")
@router.get("/api/health")
@router.get("/api/healthcheck")
def health_check():
    """Public liveness & database readiness check without revealing credentials."""
    from portfoliomaster.db.session import session_scope
    from sqlalchemy import text
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error("[Health] Database check failed: %s", e)
        return Response(
            content='{"status": "degraded", "database": "disconnected"}',
            status_code=503,
            media_type="application/json",
        )


@router.get("/api/config")
def get_config():
    """Return runtime configuration including refresh interval, batch size, and background sync status."""
    return {
        "status": "ok",
        "refresh_interval_seconds": get_refresh_interval(),
        "batch_size": get_batch_size(),
        "is_refreshing": _state.get("is_refreshing", False),
        "last_refresh_at": _state.get("last_refresh_at") or _state.get("last_refresh_time"),
        "last_refresh_result": _state.get("last_refresh_result") or _state.get("last_refresh_status"),
        "refresh_counter": _state.get("refresh_counter", 0),
        "current_batch": _state.get("current_batch", 0),
        "total_batches": _state.get("total_batches", 0),
        "processed_symbols": _state.get("processed_symbols", 0),
        "total_symbols": _state.get("total_symbols", 0),
    }
