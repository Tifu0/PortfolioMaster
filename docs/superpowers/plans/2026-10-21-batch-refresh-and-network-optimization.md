# Batch Refresh Acceleration, Progressive Streaming & Network Spam Elimination Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate redundant network chatter (`OPTIONS` & `GET /api/config` spam), accelerate Yahoo Finance batch quote fetching via vectorized multi-threaded downloads, and implement progressive Server-Sent Events (SSE) streaming updates so watchlist quotes update batch-by-batch in real time without blocking the UI.

**Architecture:**
- **Network & CORS:** Strip unnecessary non-safelisted headers (`Cache-Control: no-cache, no-store`) from client GET/HEAD requests in `frontend/lib/api.ts`, configure `max_age=86400` in FastAPI `CORSMiddleware`, add Next.js API proxy rewrites in `frontend/next.config.ts`, filter out routine `/api/config` polling logs in backend uvicorn access logger, and adjust `PortfolioContext.tsx` heartbeat to avoid idle 3s polling spam.
- **Backend Batching & Acceleration:** Refactor `YahooAdapter.fetch` to use vectorized `yf.download(tickers, period="5d", group_by="ticker", threads=True, progress=False)` with per-ticker fallback, add batch completion callbacks in `BatchRunner`, commit quotes to SQLite immediately after each batch finishes, and batch-download missing YTD historical quotes.
- **Progressive Streaming & UX:** Expose an SSE streaming endpoint `GET /api/refresh/stream` in FastAPI, provide `streamRefresh` in `frontend/lib/api.ts`, stream batch progress to `PortfolioContext` and `WatchlistTable`, update the top-right status badge and `Update Quotes` button with real-time progress (e.g. `Actualizando lote 6/11 (150/275)...`), and seamlessly re-fetch data silently per batch while preserving TanStack Table scroll, filters, sorting, and inline editing.

**Tech Stack:** Next.js 16 (App Router), React 19, @tanstack/react-table 8, FastAPI, Uvicorn, Python 3.12, SQLite, `yfinance`, Server-Sent Events (SSE).

**Spec:** Problem 1 (Excessive OPTIONS & GET /api/config requests) & Problem 2 (Slow yfinance updates & lack of progressive UI feedback).

## Global Constraints

- Do not break existing contracts tested by `frontend/scripts/verify_*.mts` or `pytest`.
- In `frontend/lib/api.ts`, ensure `getConfig()` keeps `cache: 'no-store'` as checked by `verify_api_cache.mts`.
- In `frontend/context/PortfolioContext.tsx`, retain all tokens checked by `verify_batch_auto_sync.mts` (`checkBackendSync`, `lastKnownRefreshAtRef`, `lastKnownCounterRef`, `wasRefreshingRef`, `counterChanged`, `refreshAtChanged`, `finishedRefreshing`, `refreshPortfolioData({ silent: true })`, `useMemo`).
- In `frontend/components/WatchlistContent.tsx`, retain `appConfig.is_refreshing` and `"Actualizando lote..."` as verified by `verify_batch_auto_sync.mts`.
- In `backend/api/main.py`, maintain compatibility with `POST /api/refresh` while adding `GET /api/refresh/stream`.
- Preserve TanStack table UX: no reset of scroll position, active search/filters, column sorting, or active inline edits during incremental updates.

## Review Focus

1. **CORS & Preflight elimination:** Verify GET requests from browser no longer trigger OPTIONS preflights.
2. **Terminal log quietness:** Verify uvicorn console is clean and not spammed with `/api/config` requests.
3. **Vectorized yfinance speedup:** Verify batch fetching executes multi-threaded and completes in a fraction of previous time.
4. **Immediate SQLite persistence:** Verify database has updated quotes after batch 1 without waiting for batch 11.
5. **Real-time UI streaming:** Verify the UI badge and button show live progress and table rows update batch by batch.

---

### Task 1: Eliminate CORS Preflight & `/api/config` Polling Chatter

**Files:**
- Modify: `frontend/lib/api.ts:55-320`
- Modify: `frontend/next.config.ts:1-17`
- Modify: `backend/api/main.py:90-185`
- Modify: `frontend/context/PortfolioContext.tsx:170-250`
- Test: `frontend/scripts/verify_api_cache.mts` & `frontend/scripts/verify_batch_auto_sync.mts`

- [ ] **Step 1: Clean request headers in `frontend/lib/api.ts`**
  Remove `headers: { 'Cache-Control': 'no-cache, no-store' }` from `getPositions`, `getInstruments`, `getMetrics`, `checkYahooTicker`, and `getConfig`. Ensure `cache: 'no-store'` is retained on `getConfig` and `checkYahooTicker` to satisfy `verify_api_cache.mts`. Verify GET and HEAD requests do not send `Content-Type: application/json`.
- [ ] **Step 2: Add API proxy rewrites in `frontend/next.config.ts`**
  Add `async rewrites()` mapping `/api/:path*` to `http://localhost:8000/api/:path*`.
- [ ] **Step 3: Configure CORS `max_age` and quiet access logging in `backend/api/main.py`**
  Set `max_age=86400` in `CORSMiddleware`. Add a logging filter to `logging.getLogger("uvicorn.access")` to suppress routine `/api/config` log records.
- [ ] **Step 4: Audit `PortfolioContext.tsx` polling interval**
  Adjust the polling heartbeat so that when idle, it does not poll every 3 seconds, while retaining all sync detection logic and required variable tokens for `verify_batch_auto_sync.mts`.
- [ ] **Step 5: Verify tests pass**
  Run `npx tsx scripts/verify_api_cache.mts` and `npx tsx scripts/verify_batch_auto_sync.mts`.

---

### Task 2: Vectorize `yfinance` Quotes & Incremental Commits in `BatchRunner`

**Files:**
- Modify: `src/portfoliomaster/providers/yahoo_adapter.py:200-260`
- Modify: `src/portfoliomaster/refresh/batch_runner.py:8-47`
- Modify: `backend/api/main.py:1070-1310`
- Test: `tests/test_batch_runner.py` & `backend/tests/test_api.py`

- [ ] **Step 1: Implement vectorized multi-ticker downloading in `YahooAdapter.fetch`**
  Map symbols to Yahoo format, execute `yf.download(unique_tickers, period="5d", group_by="ticker", threads=True, progress=False)`, extract price, previous close, and timestamp from dataframe columns. Fall back to individual `yf.Ticker(t)` for any missing/failed ticker.
- [ ] **Step 2: Add `on_batch_complete` callback to `BatchRunner.run`**
  Allow an optional `on_batch_complete(batch_idx, total_batches, chunk_results)` callback invoked immediately after each batch is fetched.
- [ ] **Step 3: Implement per-batch SQLite commits in `_execute_refresh_all`**
  In `_execute_refresh_all()`, pass `on_batch_complete` that immediately calls `upsert_quote(quote)` for each quote in the batch and updates `_state` with `current_batch`, `total_batches`, `processed_symbols`, `total_symbols`, `refresh_counter`.
- [ ] **Step 4: Batch missing YTD price resolution**
  In `_execute_resolve_missing_ytd_prices()`, collect all tickers missing start-of-year price for current year, download them together via `yf.download(start=..., end=...)` instead of firing sequential per-ticker requests.
- [ ] **Step 5: Verify backend tests pass**
  Run `venv\Scripts\python -u -m pytest tests/test_batch_runner.py backend/tests/test_api.py -m "not network"`.

---

### Task 3: Real-Time SSE Streaming Endpoint & Frontend Client Integration

**Files:**
- Modify: `backend/api/main.py:1310-1340`
- Modify: `frontend/lib/types.ts:40-70`
- Modify: `frontend/lib/api.ts:145-160`
- Modify: `frontend/context/PortfolioContext.tsx:15-130`
- Modify: `frontend/components/WatchlistContent.tsx:285-337`
- Modify: `frontend/components/WatchlistTable.tsx:1000-1050, 1825-1850`
- Test: `frontend/scripts/verify_phase6.mts` & `frontend/scripts/verify_batch_auto_sync.mts`

- [ ] **Step 1: Add `GET /api/refresh/stream` in `backend/api/main.py`**
  Implement an SSE endpoint returning `StreamingResponse(event_generator(), media_type="text/event-stream")` emitting events for `start`, `batch`, and `complete`.
- [ ] **Step 2: Extend `AppConfig` and add `streamRefresh` in `frontend/lib/types.ts` & `frontend/lib/api.ts`**
  Add `current_batch?: number`, `total_batches?: number`, `processed_symbols?: number`, `total_symbols?: number` to `AppConfig`. Implement `streamRefresh(onProgress)` in `api.ts`.
- [ ] **Step 3: Expose batch progress in `PortfolioContext`**
  Add `batchProgress` state and share it in `PortfolioContextType`.
- [ ] **Step 4: Update UI progress indicators**
  - In `WatchlistContent.tsx`: Display `Actualizando lote ${current_batch}/${total_batches} (${processed_symbols}/${total_symbols})...` in the top-right status badge.
  - In `WatchlistTable.tsx`: Update `handleBatchRefresh` to use `streamRefresh`, update progress state on each batch, silently reload positions and metrics per batch, and display `Actualizando ${currentBatch}/${totalBatches} (${processed}/${total})...` in the button.
- [ ] **Step 5: Verify table state preservation**
  Verify table scroll, column sorting, active filter, and open inline edit (`editingDateTicker`) are untouched while rows update.

---

### Task 4: Full Verification & Regression Testing

**Files:**
- Run all test suites
- Review git diff

- [ ] **Step 1: Run frontend test suite (`npm test`)**
  Ensure all 15 verification scripts pass cleanly.
- [ ] **Step 2: Run backend test suite (`pytest -m "not network"`)**
  Ensure all 77 pytest tests pass cleanly.
- [ ] **Step 3: End-to-end review**
  Verify zero console spam, zero CORS preflight for GETs, fast batch downloading, and fluid live updates.
