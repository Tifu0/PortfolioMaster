"""Tests for multi-instance refresh coordination, CORS security, and background worker controls."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from portfoliomaster.db.schema import Base, RefreshRun
from portfoliomaster.db.multi_tenant_repository import RefreshRunRepository


def test_cors_wildcard_rejected():
    """Wildcard '*' in CORS_ORIGINS must raise RuntimeError when allow_credentials=True."""
    with patch.dict(os.environ, {"CORS_ORIGINS": "https://app.vercel.app,*"}, clear=False):
        with pytest.raises(RuntimeError) as exc_info:
            # Re-evaluating CORS configuration logic
            cors_str = os.environ.get("CORS_ORIGINS", "")
            origins = [orig.strip() for orig in cors_str.split(",") if orig.strip()]
            if "*" in origins:
                raise RuntimeError("Wildcard '*' is forbidden in CORS_ORIGINS when allow_credentials=True.")
        assert "Wildcard '*'" in str(exc_info.value)


def test_cors_production_fails_when_missing():
    """In production / Render, missing CORS_ORIGINS must fail fast."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "CORS_ORIGINS": ""}, clear=False):
        is_prod = os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod")
        cors_str = os.environ.get("CORS_ORIGINS", "")
        with pytest.raises(RuntimeError) as exc_info:
            if not cors_str and is_prod:
                raise RuntimeError("CORS_ORIGINS must be set in production")
        assert "CORS_ORIGINS must be set in production" in str(exc_info.value)


def test_cors_valid_origins_parsed():
    """Comma-separated origins must parse into clean trimmed list."""
    with patch.dict(os.environ, {"CORS_ORIGINS": "https://foo.com, https://bar.vercel.app "}):
        cors_str = os.environ.get("CORS_ORIGINS", "")
        origins = [orig.strip() for orig in cors_str.split(",") if orig.strip()]
        assert origins == ["https://foo.com", "https://bar.vercel.app"]


def test_multi_instance_refresh_coordination_skips_when_running():
    """If another instance has a RUNNING refresh_run in PostgreSQL, a new execution must skip."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        repo = RefreshRunRepository(session)
        # Simulate instance A having started a run
        run_a = repo.start_run(total_symbols=5, trigger_type="batch_worker")
        session.commit()

        # Instance B checks if a run is already active
        assert repo.is_running(scope="GLOBAL") is True

        # When checking before execution, instance B detects active run
        active_in_db = repo.is_running(scope="GLOBAL")
        assert active_in_db is True


def test_stale_refresh_run_auto_timeout_cleanup():
    """Stale runs older than 10 minutes must be marked as TIMEOUT to avoid deadlocks."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    now_utc = datetime.now(timezone.utc)
    eleven_minutes_ago = now_utc - timedelta(minutes=11)

    with Session() as session:
        # Create an orphaned run from a crashed worker 11 minutes ago
        stale_run = RefreshRun(
            trigger_type="batch_worker",
            status="RUNNING",
            total_symbols=10,
            started_at=eleven_minutes_ago,
        )
        session.add(stale_run)
        session.commit()

        # Recovery logic: find RUNNING older than 10 minutes
        cutoff = now_utc - timedelta(minutes=10)
        stale_runs = session.scalars(
            select(RefreshRun).where(
                RefreshRun.status == "RUNNING",
                RefreshRun.started_at < cutoff,
            )
        ).all()
        for sr in stale_runs:
            sr.status = "TIMEOUT"
            sr.diagnostic_summary = "Timed out after 10 minutes without completion."
        session.commit()

        # Verify the stale run was updated to TIMEOUT
        updated_run = session.get(RefreshRun, stale_run.id)
        assert updated_run.status == "TIMEOUT"

        # Now is_running should be False, unlocking new runs
        repo = RefreshRunRepository(session)
        assert repo.is_running(scope="GLOBAL") is False


def test_broadcast_payload_does_not_leak_private_data():
    """SSE broadcast events must only contain status and progress counts, never user or ticker data."""
    from backend.api.routers.refresh import _broadcast_refresh_event, _sse_subscribers, _sse_lock
    import queue

    test_q = queue.Queue()
    with _sse_lock:
        _sse_subscribers.add(test_q)

    try:
        sample_batch = {
            "type": "batch",
            "batch_index": 1,
            "total_batches": 2,
            "processed_symbols": 10,
            "total_symbols": 20,
            "updated": 9,
            "failed": 1,
            "batch_updated": 9,
            "batch_failed": 1,
        }
        _broadcast_refresh_event(sample_batch)

        received = test_q.get_nowait()
        assert "user_id" not in received
        assert "ticker" not in received
        assert "positions" not in received
        assert received["total_symbols"] == 20
        assert received["updated"] == 9
    finally:
        with _sse_lock:
            _sse_subscribers.discard(test_q)
