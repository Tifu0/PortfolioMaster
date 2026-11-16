# Supabase Egress Optimization Implementation Plan (6.79GB -> <1GB/month)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Supabase uncached egress from 6.79GB/month to <1GB/month by eliminating continuous 24/7 background refresh during idle times, eliminating per-batch frontend query storms, replacing pre-SELECT ORM upserts with native zero-read `ON CONFLICT` bulk upserts, implementing in-memory caching with ETag/304 in FastAPI, and disabling redundant Supabase Realtime WAL subscriptions.

**Architecture:** 
- In FastAPI: Introduce thread-safe in-memory response cache with ETag/304 for `/api/positions` and `/api/metrics`, and an idle client activity gate in `background_refresh_loop` that pauses refreshes after 15 minutes without active requests or SSE connections.
- In Database Repository: Replace `SELECT * ... WHERE provider_symbol IN (...)` with a single native `INSERT ... ON CONFLICT (provider_symbol) DO UPDATE SET ...` bulk statement with delta filtering to skip DB writes for unchanged quotes.
- In Next.js Frontend: Remove `refreshPortfolioData()` from every SSE `batch` tick, merge quote deltas directly in-memory, trigger reload only on `complete`, and remove the redundant Supabase Realtime `postgres_changes` listener on `market_quotes`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL (Supabase / Supavisor pooler), SQLite (local fallback), Next.js 16 (React 19), Server-Sent Events (SSE).

**Spec:** Emergency Supabase Egress Optimization for PortfolioMaster.

## Estimated Egress Savings
- Vector 1 (Smart Idle-Aware Background Refresh Scheduler): **~1.8 GB/month**
- Vector 2 & 5 (Eliminate Frontend Per-Batch Storm + In-Memory Read Cache with ETag): **~2.2 GB/month**
- Vector 3 (Zero-Read `ON CONFLICT` Bulk Upsert + In-Memory Delta Filtering): **~1.5 GB/month**
- Vector 4 (Disable Redundant Supabase Realtime Subscriptions on `market_quotes`): **~1.2 GB/month**
- Vector 6 (Increase Batch Size to 50 + Connection Pooling Optimization): **~0.3 GB/month**
- **TOTAL ESTIMATED SAVINGS:** **~7.0 GB/month (Brings usage from 6.79 GB to < 0.6 GB/month)**

## Global Constraints
- Preserve 100% functionality and parity between Supabase PostgreSQL and local SQLite (`portfolio.db`).
- All 151 existing backend tests and all frontend verification scripts must pass without regressions.
- Non-destructive quote updates: existing valid prices and previous close must NEVER be overwritten by errors or nulls.
- Authoritative financial formulas must remain strictly server-side in Python (`portfoliomaster.core.calculations`).

## Review Focus
1. **Delta filtering edge cases**: Ensure the first fetch of a quote always writes to DB, and only unchanged consecutive quotes are filtered out.
2. **Cache invalidation correctness**: Ensure any manual edit, ticker creation, deletion, or new quote batch immediately invalidates the in-memory positions cache.
3. **HTTP 304 Not Modified contract**: Ensure clients sending matching `If-None-Match` receive HTTP 304 with an empty body, saving downstream bandwidth.
4. **SSE reconnect & idle wakeup**: Ensure when a user opens the dashboard after hours of idle time, an immediate smooth refresh is allowed and client activity wakes the scheduler.
5. **Multi-tenant isolation**: In-memory cache keys must be strictly segregated by `user_id`.

---

### Task 1: Zero-Read `ON CONFLICT` Bulk Upsert & Delta Write-Only Filter

**Files:**
- Create: `tests/test_quote_delta_and_upsert.py`
- Modify: `src/portfoliomaster/db/multi_tenant_repository.py:567-657`

**Interfaces:**
- Consumes: `quotes_data: List[dict]` containing provider_symbol, price, previous_close, quote_timestamp, status, error_message.
- Produces: `upsert_market_quotes_batch(quotes_data: List[dict]) -> List[dict]` executing a single native `ON CONFLICT (provider_symbol) DO UPDATE` without pre-`SELECT`, skipping quotes whose price/status have not changed.

- [ ] **Step 1: Write the failing test for delta filtering and zero-read upsert**

```python
# tests/test_quote_delta_and_upsert.py
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from portfoliomaster.db.multi_tenant_repository import (
    GlobalMarketQuotesRepository,
    filter_unchanged_quotes,
    clear_quote_delta_cache,
)

def test_delta_filter_skips_unchanged_quotes():
    clear_quote_delta_cache()
    quotes = [
        {"provider_symbol": "AAPL", "price": Decimal("230.00"), "previous_close": Decimal("225.00"), "status": "FRESH"},
        {"provider_symbol": "MSFT", "price": Decimal("420.00"), "previous_close": Decimal("415.00"), "status": "FRESH"},
    ]
    # First time: all quotes must pass through
    filtered = filter_unchanged_quotes(quotes)
    assert len(filtered) == 2

    # Second time with identical data: both should be skipped
    filtered_second = filter_unchanged_quotes(quotes)
    assert len(filtered_second) == 0

    # Third time with changed AAPL price: only AAPL should pass through
    changed_quotes = [
        {"provider_symbol": "AAPL", "price": Decimal("231.50"), "previous_close": Decimal("225.00"), "status": "FRESH"},
        {"provider_symbol": "MSFT", "price": Decimal("420.00"), "previous_close": Decimal("415.00"), "status": "FRESH"},
    ]
    filtered_third = filter_unchanged_quotes(changed_quotes)
    assert len(filtered_third) == 1
    assert filtered_third[0]["provider_symbol"] == "AAPL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\pytest tests/test_quote_delta_and_upsert.py -v`
Expected: FAIL with ImportError: cannot import name 'filter_unchanged_quotes'

- [ ] **Step 3: Implement `filter_unchanged_quotes` and zero-read native SQL upsert in `multi_tenant_repository.py`**

Implement in-memory delta cache dictionary and replace pre-`SELECT` in `upsert_market_quotes_batch` with native SQL `INSERT ... ON CONFLICT (provider_symbol) DO UPDATE SET ...` compatible with SQLite and PostgreSQL.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\pytest tests/test_quote_delta_and_upsert.py tests/test_phase3_provider_refresh_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/portfoliomaster/db/multi_tenant_repository.py tests/test_quote_delta_and_upsert.py
git commit -m "perf(db): implement zero-read ON CONFLICT bulk upsert and delta filtering"
```

---

### Task 2: In-Memory Read Cache & ETag / 304 Support for `/api/positions` & `/api/metrics`

**Files:**
- Create: `backend/tests/test_positions_cache.py`
- Modify: `backend/api/routers/positions.py`
- Modify: `backend/api/routers/refresh.py`
- Modify: `backend/api/routers/instruments.py`

**Interfaces:**
- Consumes: `get_positions` and `get_metrics` request context.
- Produces: `invalidate_positions_cache(user_id=None)` to clear cache; returns cached dicts with `ETag` and responds with HTTP 304 when `If-None-Match` matches.

- [ ] **Step 1: Write the failing test for in-memory caching and ETag**

```python
# backend/tests/test_positions_cache.py
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api.routers.positions import invalidate_positions_cache, get_cache_stats

client = TestClient(app)

def test_consecutive_positions_calls_serve_from_cache():
    invalidate_positions_cache()
    # First call - cache miss
    res1 = client.get("/api/positions")
    assert res1.status_code == 200
    etag1 = res1.headers.get("ETag")
    assert etag1 is not None

    stats1 = get_cache_stats()
    assert stats1["hits"] == 0

    # Second call - cache hit
    res2 = client.get("/api/positions")
    assert res2.status_code == 200
    assert res2.headers.get("ETag") == etag1
    stats2 = get_cache_stats()
    assert stats2["hits"] >= 1

    # Third call with If-None-Match - 304 Not Modified
    res3 = client.get("/api/positions", headers={"If-None-Match": etag1})
    assert res3.status_code == 304
    assert res3.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\pytest backend/tests/test_positions_cache.py -v`
Expected: FAIL

- [ ] **Step 3: Implement in-memory cache and ETag handling in `backend/api/routers/positions.py`**

Create thread-safe cache dictionary keyed by `(user_id, active_only)`. Compute ETag (SHA-256 or MD5 hash of response or version). Check `If-None-Match` and return 304. Update `invalidate_positions_cache()` to clear the cache. Call `invalidate_positions_cache()` in `instruments.py` (create/update/delete/rename) and `refresh.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\pytest backend/tests/test_positions_cache.py backend/tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/routers/positions.py backend/api/routers/refresh.py backend/api/routers/instruments.py backend/tests/test_positions_cache.py
git commit -m "perf(api): add in-memory read cache and ETag/304 support for positions and metrics"
```

---

### Task 3: Idle-Aware Background Refresh Scheduler & Default Settings

**Files:**
- Create: `backend/tests/test_idle_refresh.py`
- Modify: `backend/api/main.py`
- Modify: `backend/api/routers/refresh.py`
- Modify: `src/portfoliomaster/core/config.py`
- Modify: `render.yaml`

**Interfaces:**
- Consumes: Client activity events and SSE subscriber count.
- Produces: `is_system_idle() -> bool` which pauses background refresh when idle > 15 minutes.

- [ ] **Step 1: Write the failing test for idle awareness**

```python
# backend/tests/test_idle_refresh.py
import time
from backend.api.activity import (
    record_client_activity,
    get_last_client_activity,
    is_scheduler_idle,
    reset_client_activity,
)

def test_idle_detection_after_15_minutes():
    reset_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900) is True

    record_client_activity()
    assert is_scheduler_idle(idle_timeout_seconds=900) is False

    # Simulate past timestamp > 15 minutes ago
    from backend.api.activity import _set_last_client_activity
    _set_last_client_activity(time.time() - 905)
    assert is_scheduler_idle(idle_timeout_seconds=900) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\pytest backend/tests/test_idle_refresh.py -v`
Expected: FAIL

- [ ] **Step 3: Implement client activity tracking in `backend/api/activity.py` and integrate into `backend/api/main.py`**

- Create `backend/api/activity.py` with `record_client_activity()`, `is_scheduler_idle()`, and active subscriber tracking.
- Call `record_client_activity()` in FastAPI middleware or `/api/positions`, `/api/metrics`, `/api/instruments`.
- In `background_refresh_loop()`, if `is_scheduler_idle(idle_timeout_seconds=900)` and no SSE subscribers exist, log idle state, sleep 60s, and skip DB queries.
- Update `DEFAULT_BATCH_SIZE` to 50 in `config.py` and `BATCH_SIZE: 50` in `render.yaml`.
- Update `REFRESH_INTERVAL_SECONDS` cloud default to 300s in `render.yaml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\pytest backend/tests/test_idle_refresh.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/activity.py backend/api/main.py src/portfoliomaster/core/config.py render.yaml backend/tests/test_idle_refresh.py
git commit -m "perf(scheduler): add idle-aware background refresh gating and update batch defaults"
```

---

### Task 4: Frontend Quote Delta In-Memory Merge & Remove Redundant Supabase Realtime

**Files:**
- Modify: `backend/api/routers/refresh.py` (include `quotes` deltas in SSE `batch` payload)
- Modify: `frontend/context/PortfolioContext.tsx`
- Modify: `frontend/lib/api.ts` (ETag caching for positions/metrics)

**Interfaces:**
- Consumes: SSE `batch` event with `quotes: Record<string, { price, previous_close, status }>`.
- Produces: In-memory position price updates on `batch` events; eliminates calls to `refreshPortfolioData` during intermediate batches; removes Supabase Realtime `postgres_changes` listener on `market_quotes`.

- [ ] **Step 1: Check existing frontend test contracts and write verification script**

Ensure all verification scripts in `frontend/scripts/` continue to pass, specifically `verify_batch_auto_sync.mts` and `verify_portfolio_context.mts`.

- [ ] **Step 2: Enrich SSE `batch` event payload in `backend/api/routers/refresh.py`**

Add `quotes` dictionary to `batch_payload` containing `price`, `previous_close`, and `status` for valid symbols in the chunk.

- [ ] **Step 3: Update `frontend/context/PortfolioContext.tsx`**

- In SSE listener: on `batch` event, do NOT trigger `refreshPortfolioData({ silent: true })`. Instead, update `batchProgress` and merge quote prices into `positions` state in-memory.
- On `complete` event: trigger a single `refreshPortfolioData({ silent: true })` (which hits the backend cache/ETag).
- Remove the Supabase Realtime `postgres_changes` subscription on `market_quotes`.
- In `frontend/lib/api.ts`: store last known ETag for `/api/positions` and `/api/metrics` and send `If-None-Match`. On 304, reuse cached payload.

- [ ] **Step 4: Run frontend verification tests**

Run: `cd frontend && npm test -- --run`
Expected: PASS (All verification scripts pass)

- [ ] **Step 5: Commit**

```bash
git add backend/api/routers/refresh.py frontend/context/PortfolioContext.tsx frontend/lib/api.ts
git commit -m "perf(frontend): merge SSE quote deltas in-memory and disable redundant Supabase Realtime"
```

---

### Task 5: Supabase Supavisor Pooler Verification & Documentation

**Files:**
- Modify: `src/portfoliomaster/db/session.py`
- Modify: `docs/deployment.md`

**Interfaces:**
- Consumes: Supabase `DATABASE_URL` with transaction pooling (port 6543).
- Produces: Stable SQLAlchemy engine with `prepare_threshold=None` and connection pool settings.

- [ ] **Step 1: Verify `src/portfoliomaster/db/session.py` pooler arguments**

Confirm `pool_pre_ping=True`, `pool_recycle=300`, `pool_size=5`, and `prepare_threshold=None` for psycopg 3 on port 6543.

- [ ] **Step 2: Document Supabase Supavisor connection string configuration in `docs/deployment.md`**

Document the exact `DATABASE_URL` format:
`postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres?sslmode=require`

- [ ] **Step 3: Run full backend and frontend test suites**

Run: `.\venv\Scripts\pytest` and `cd frontend && npm test -- --run`
Expected: 100% PASS

- [ ] **Step 4: Commit**

```bash
git add src/portfoliomaster/db/session.py docs/deployment.md
git commit -m "docs(deploy): document Supavisor transaction pooler config and verify session engine"
```
