# Specification 04: Concurrency, Multi-Tenant Refresh/SSE Isolation & Query Performance (U4)

## 1. Scope & Boundaries
- **In Scope (U4):**
  - Event-loop non-blocking delegation (`asyncio.to_thread`), thread-safety (`threading.local()`, `threading.Lock()`), releasing `session_scope()` around all Yahoo Finance HTTP I/O, and removing redundant `session.commit()` calls inside `session_scope()`.
  - Read-only `/health*` checks without `COMMIT` and multi-worker-safe `GET /api/config` backed by `refresh_runs`.
  - Multi-tenant isolation for `POST /api/refresh` (`can_user_refresh()`, tenant-scoped `force=true`, lock-protected `_state`, fixed `resolve-missing-*` invocation), decoupling `last_attempt_at` updates from `filter_unchanged_quotes`, UTC-aware cooldown timestamps, and non-blocking tenant-filtered SSE via `asyncio.Queue(maxsize=100)` (`GET /api/refresh/stream` pure subscriber + surgical frontend `streamRefresh` alignment).
  - Elimination of N+1 queries in PG import/restore and SQLite import/export, `noload(UserInstrument.quote)` on `GET /api/instruments`, single-statement `DELETE ... RETURNING id`, elimination of `pd.read_sql_query` / `df.iterrows()` in `positions.py`, lightweight SQL projection for `GET /api/positions` and `GET /api/metrics`, and bounded LRU+TTL caches.
- **Out of Scope (U5–U7):**
  - Do NOT split `instruments.py` or `refresh.py` into submodules, create `core/parsing.py`, unify `if is_multi_tenant_db()` branches behind a single repository abstraction, or reorganize `tests/` + `backend/tests/` (U5).
  - Do NOT modify CSS, responsive layout, i18n, accessibility, or split `WatchlistTable` / `ManualEntryModal` (U6/U7).
- **Permitted Frontend Surgical Exception:**
  - Because `GET /api/refresh/stream` becomes a pure read-only SSE subscriber without triggering refreshes on `GET`, `streamRefresh` in `frontend/lib/api.ts` (and its proxy guard / verification tests if needed) is updated minimally to subscribe via `GET /api/refresh/stream` first and trigger `POST /api/refresh?background=true`, validated by `lint`, `tsc`, `npm test`, and `npm run build`.

---

## 2. Sub-unit U4.1: Event Loop, Thread-Safety & DB Pool Hygiene

### 2.1 Event-Loop Protection (`async def` Boundaries)
1. **`background_refresh_loop` & `lifespan` (`backend/api/main.py`):**
   - Extract synchronous database existence checks (`session_scope()` count in multi-tenant mode; `get_all_instruments()` in SQLite mode) into `_has_active_instruments() -> bool` and invoke via `await asyncio.to_thread(_has_active_instruments)`.
   - Offload synchronous startup DB readiness checks (`SELECT 1` / `init_db()`) in `lifespan` via `await asyncio.to_thread(...)`.
2. **`POST /api/import/preview` (`backend/api/routers/import_export.py`):**
   - Keep async chunked upload reading (`await file.read(65536)` with `MAX_UPLOAD_BYTES` enforcement).
   - Offload temporary file creation, write, `import_spreadsheet(...)`, and `os.remove` cleanup into a synchronous helper `_parse_import_bytes(content: bytes, ext: str, filename: str, max_rows: int)` executed via `await asyncio.to_thread(...)`.

### 2.2 Thread-Safety for Shared Singletons
1. **`YahooAdapter` (`src/portfoliomaster/providers/yahoo_adapter.py`):**
   - Replace the single global `_RESILIENT_SESSION` shared across `ThreadPoolExecutor` workers with `threading.local()` (`_THREAD_LOCAL`) in `get_resilient_session()` so each thread owns an isolated `requests.Session` configured with identical `Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "HEAD"], raise_on_status=False)`, `HTTPAdapter(max_retries=..., pool_connections=10, pool_maxsize=20)`, and browser `User-Agent`.
   - Protect `_CRUMB_RATE_LIMITED_UNTIL` reads/writes with `_CRUMB_LOCK = threading.Lock()`.
2. **`_JWKS_CLIENT` (`backend/api/common.py`):**
   - Protect lazy initialization/URL-change refresh of `_JWKS_CLIENT` in `get_jwks_client(supabase_url)` with `_JWKS_CLIENT_LOCK = threading.Lock()` using double-checked locking.
3. **`_ENGINE` & `_SESSION_FACTORY` (`src/portfoliomaster/db/session.py`):**
   - Protect singleton initialization in `get_engine()` and `get_session_factory()` with `_ENGINE_LOCK = threading.Lock()`.

### 2.3 DB Connection Pool Hygiene & Zero Duplicate `commit()`
1. **Golden Rule — Zero Network I/O Inside `session_scope()`:**
   - Refactor all endpoints/workers performing Yahoo Finance network I/O to a strict 3-phase lifecycle:
     1. **Read Phase:** Open `session_scope()`, read required fields into plain DTOs/primitives/tuples (using `noload(UserInstrument.quote)` when quote is not needed), and exit `session_scope()` immediately.
     2. **Network Phase:** Perform all Yahoo HTTP calls (`adapter.fetch`, `_fetch_historical_quote_and_date`, `_fetch_start_of_year_quote`, `BatchRunner.run`) with **zero** database sessions open.
     3. **Write Phase:** Open a brief `session_scope()`, persist changes in batch, and exit `session_scope()` (committing automatically once).
   - Affected endpoints/functions:
     - `backend/api/routers/refresh.py`: `_execute_refresh_all` (PG mode: Phase 1 read symbols/staleness & start `RefreshRun` -> exit session -> `BatchRunner.run()` opens brief per-batch `session_scope()` inside `on_batch_pg` after each Yahoo batch returns -> Phase 3 brief `session_scope()` to mark `RefreshRun` `COMPLETED`/`FAILED`) and `refresh_single_instrument` (`POST /api/instruments/{ticker}/refresh`).
     - `backend/api/routers/instruments.py`: `fetch_analysis_price_endpoint`, `fetch_ytd_price_endpoint`, `resolve_missing_analysis_prices`, and `resolve_missing_ytd_prices` (parallelize candidate Yahoo lookups via `ThreadPoolExecutor(max_workers=min(8, len(candidates)))` outside any DB session, then persist all resolved rows in one short `session_scope()`).
2. **Eliminate Redundant `session.commit()` Inside `session_scope()`:**
   - Remove all trailing/redundant `session.commit()` calls inside `with session_scope() as session:` blocks (`backup.py:52`, `import_export.py:128`, `instruments.py:764, 947, 1027, 1119, 1186`, `refresh.py:425, 722, 909, 917, 930`), relying on `session_scope()`'s exit commit (and `session.flush()` only when an intermediate PK/flush is needed).
3. **Read-Only Healthcheck & Multi-Worker `GET /api/config` (`backend/api/routers/config.py`):**
   - `/health`, `/healthcheck`, `/api/health`, `/api/healthcheck`: execute `SELECT 1` via `get_engine().connect()` (with `execution_options(isolation_level="AUTOCOMMIT")` where supported or non-mutating connection close) so health probes emit zero `COMMIT` statements.
   - `GET /api/config`: in multi-tenant mode, query `RefreshRun` (read-only) for any active `RUNNING` run or latest run metadata to report accurate cross-worker `is_refreshing` / progress / `last_refresh_at`, merging safely with `_state` under `_state_lock` when no DB run exists or in SQLite mode.

---

## 3. Sub-unit U4.2: Multi-Tenant Refresh Isolation, UTC Cooldown & SSE

### 3.1 Multi-Tenant Refresh & `force=true` Isolation (`backend/api/routers/refresh.py`)
1. **Per-Tenant Scope:**
   - `POST /api/refresh` passes the authenticated `user_id` into `_execute_refresh_all(user_id=user_id, force=force)`.
   - In multi-tenant mode, when `user_id` is provided:
     - Query **only** active `UserInstrument` rows where `UserInstrument.user_id == user_id` (with `noload(UserInstrument.quote)`).
     - `force=True` refreshes **only** `user_id`'s active symbols and clears **only** those symbols from `_LAST_KNOWN_QUOTES` via `clear_quote_delta_cache(symbols=unique_symbols)` — never wiping other tenants' delta state or fetching symbols exclusive to other tenants.
     - Enforce per-tenant anti-spam cooldown via `RefreshRunRepository(session).can_user_refresh(user_id, cooldown_seconds=STALE_THRESHOLD_SECONDS)` (or reject concurrent active runs for that `user_id` even if `force=True`, while allowing `force=True` to bypass the time cooldown when no run is `RUNNING`). When blocked by time cooldown (`not force`), return `{"status": "fresh", "message": "Precios actualizados recientemente", "detail": cooldown_msg, "refreshed_count": 0, ...}` and emit a tenant-scoped `"complete"` (`status="fresh"`) event.
     - Create `RefreshRun` with `user_id=user_id` and `trigger_type="manual"` (coordinate via `is_running(scope="USER", user_id=user_id)` and a per-user in-process lock, rather than blocking unrelated tenants globally).
   - When `user_id is None` (background scheduler in `main.py`): coordinate globally with `scope="GLOBAL"`.
2. **Thread-Safe `_state` Access:**
   - Guard all reads and mutations of `_state` (in `refresh.py` and `config.py`) with `_state_lock = threading.Lock()`.
3. **Fix Broken `refresh.py:673, 681` Calls & PG Parity:**
   - Extract reusable non-FastAPI helpers `_resolve_missing_analysis_prices(user_id: Optional[uuid.UUID])` and `_resolve_missing_ytd_prices(user_id: Optional[uuid.UUID])` in `instruments.py` (callable both by HTTP endpoints and `refresh.py`).
   - Call them cleanly in both SQLite and multi-tenant PG branches of `_execute_refresh_all` (when `user_id` is present, or per affected tenant) without `Depends(...)` errors.

### 3.2 Cooldown `last_attempt_at` Fix & UTC Consistency
1. **Decouple `last_attempt_at` from `filter_unchanged_quotes`:**
   - In `GlobalMarketQuotesRepository`, add `touch_last_attempt_at(symbols: List[str], attempted_at: datetime) -> int` executing a single bulk `UPDATE market_quotes SET last_attempt_at = :ts WHERE provider_symbol IN (...)` (without altering `price`, `previous_close`, `status`, or `last_valid_fetched_at`).
   - In `refresh.py` (`on_batch_pg`), compute `deltas_to_write = filter_unchanged_quotes(batch_quotes_payload)`. Persist `deltas_to_write` via `upsert_market_quotes_batch`, and for any symbol in the batch that was filtered out (and already exists in `market_quotes`), invoke `touch_last_attempt_at(unchanged_symbols, now_utc)`. If any symbol is missing from `market_quotes` (e.g., stale in-memory cache), include it in `upsert_market_quotes_batch`. Result: repeated identical prices still update `last_attempt_at`, honoring the 120s cooldown.
2. **Strict UTC Timestamps:**
   - In `YahooAdapter` (`src/portfoliomaster/providers/yahoo_adapter.py`), replace all `datetime.now()` / `datetime.fromtimestamp(x)` with `datetime.now(timezone.utc)` / `datetime.fromtimestamp(x, tz=timezone.utc)`, and ensure naive pandas/yfinance datetimes are normalized to `timezone.utc`.
   - In `backend/api/routers/instruments.py` (L859–860) and `refresh.py`, ensure all `fetched_at`, `quote_timestamp` fallbacks, and `last_attempt_at` values are UTC-aware `datetime.now(timezone.utc)` so the 30s SQLite and 120s PG cooldowns never skew across host timezones.

### 3.3 Pure-Subscriber SSE Architecture (`asyncio.Queue` + Tenant Isolation)
1. **Separate Mutation from Subscription:**
   - `GET /api/refresh/stream` is strictly read-only: it NEVER spawns `_execute_refresh_all` or mutates refresh state.
   - `POST /api/refresh` accepts `background: bool = False` and `force: bool = False`. When `background=True`, it starts `_execute_refresh_all(user_id=user_id, force=force)` in a daemon thread (or returns immediately if already running / blocked by cooldown) and returns `{"status": "triggered", ...}` (or `in_progress` / `fresh`).
2. **Non-Blocking `asyncio.Queue(maxsize=100)` Subscribers:**
   - Replace `_sse_subscribers: set[queue.Queue]` and `await asyncio.to_thread(q.get, timeout=1.0)` with `_SSESubscriber` instances (`queue: asyncio.Queue[dict]` with `maxsize=100`, `loop: asyncio.AbstractEventLoop`, `user_id: uuid.UUID`, `allowed_symbols: Optional[frozenset[str]]`).
   - In `event_generator()`, await `await asyncio.wait_for(sub.queue.get(), timeout=1.0)` and yield `": keepalive\n\n"` on `asyncio.TimeoutError`, removing the subscriber in `finally:`.
   - `_broadcast_refresh_event(payload: dict, target_user_id: Optional[uuid.UUID] = None)` delivers events from synchronous worker threads via `sub.loop.call_soon_threadsafe(_enqueue_nonblocking, sub.queue, filtered_payload)`, dropping the oldest item on `asyncio.QueueFull` so slow clients never stall producers.
3. **Strict Tenant Filtering & Error Sanitization:**
   - When `target_user_id` is set (user-initiated refresh), broadcast ONLY to subscribers with `sub.user_id == target_user_id`.
   - When `target_user_id is None` (global background refresh), filter `payload["quotes"]` (if present) to `sub.allowed_symbols` for multi-tenant subscribers so no tenant ever receives quote deltas for tickers they do not hold; never include raw `str(e)` in SSE `"error"` payloads (`"Refresh failed due to an internal error."` in production, sanitized summary otherwise).
4. **Surgical Frontend Alignment (`frontend/lib/api.ts`):**
   - Update `streamRefresh(onProgress)` to avoid the `POST`/`GET` event-loss race condition using **subscribe-first**:
     1. Open `GET /api/refresh/stream` (`Accept: text/event-stream`, `cache: 'no-store'`).
     2. Read the initial `"connected"` SSE frame (confirming server-side subscriber registration).
     3. If `!connected.is_refreshing`, trigger `POST /api/refresh?background=true` via `authFetch`. (If `POST` returns a synchronous terminal state such as `"fresh"` without streaming a `"complete"` event, synthesize/return cleanly.)
     4. Continue reading SSE frames until `"complete"` or `"error"`, resolving/rejecting cleanly and releasing the reader lock in `finally`.

---

## 4. Sub-unit U4.3: Query Optimization, N+1 Elimination & Bounded Caches

### 4.1 Explicit Query Budgets (`max_queries`)
| Operation | Engine / Mode | Baseline (Measured) | Target Budget (`max_queries`) | Strategy |
|---|---|---|---|---|
| `import_or_restore_user_watchlist(N=25)` | PG / SQLAlchemy | ~`4N` (80 for N=20) | `<= 8` queries (`O(1)`) | 1 `DELETE` (if `replace_all`), 1 `SELECT` existing `user_instruments` + 1 `SELECT` existing `market_quotes` (`IN`), 1 bulk `INSERT ... ON CONFLICT (provider_symbol) DO NOTHING` for missing `market_quotes`, 1 bulk `INSERT ... ON CONFLICT (user_id, upper(user_ticker)) DO UPDATE` (chunked at 200 rows) |
| `POST /api/import/confirm(N=25)` | SQLite | `N` connections & commits | `<= 2` connections / `1` batch tx | Single `sqlite3` connection & transaction using `executemany` `INSERT ... ON CONFLICT(user_ticker) DO UPDATE` |
| `get_export_records(N=20)` | SQLite | `1 + N` (21 queries) | `1` query | Single `SELECT i.*, q.* FROM instruments i LEFT JOIN quotes q ON q.instrument_id = i.id WHERE i.active = 1` |
| `GET /api/instruments` | PG / SQLAlchemy | 1 query with unused `LEFT OUTER JOIN market_quotes` | `1` query, `0` joins | `options(noload(UserInstrument.quote))` |
| `DELETE /api/instruments/{ticker}` | PG / SQLAlchemy | `2` queries (`SELECT`+`JOIN` then `DELETE`) | `1` query | `DELETE FROM user_instruments WHERE user_id = :uid AND upper(user_ticker) = :t RETURNING id` |
| `GET /api/positions` (cache miss) | PG / SQLite | 1 ORM graph / `pd.read_sql_query` + `df.iterrows()` | `1` query, `0` `iterrows()` | PG: column projection / `user_positions_view` without heavy ORM graph; SQLite: direct `sqlite3.Row` iteration |
| `GET /api/metrics` (cache miss) | PG / SQLite | Calls `get_positions(user_id)` with `Query(None)` bug | `1` lightweight query | Explicit `active_only=None` semantics; query only required columns (`user_ticker, company_name, currency, latest_price, previous_close`) / SQL KPI projection |

### 4.2 Bulk `ON CONFLICT` Details (`src/portfoliomaster/db/multi_tenant_repository.py`)
- **`import_or_restore_user_watchlist`:**
  1. Pre-parse and deduplicate input rows in Python by `upper(user_ticker)` (last occurrence wins, matching sequential overwrite semantics).
  2. If `replace_all`: `DELETE FROM user_instruments WHERE user_id = :uid`.
  3. Collect unique `provider_symbol` values and issue bulk `INSERT INTO market_quotes (...) VALUES (...) ON CONFLICT (provider_symbol) DO NOTHING` (chunked at 200 rows; dialect-safe for PostgreSQL and SQLite).
  4. Issue bulk `INSERT INTO user_instruments (...) VALUES (...) ON CONFLICT (user_id, upper(user_ticker)) DO UPDATE SET ...` (chunked at 200 rows) preserving existing `exchange`/`currency`/`company_name`/`comment`/reference fields when omitted from update payload (`item` key absence vs explicit `None` parity).
  5. Note: On SQLite test DBs and PostgreSQL >= 9.5, `ON CONFLICT (user_id, upper(user_ticker))` targets `idx_user_instruments_user_upper_ticker` directly, handling case-insensitive updates (`aapl` -> `AAPL`) in `O(1)` round-trips.

### 4.3 `positions.py` & `GET /api/metrics` Optimization + Bounded Caches
1. **Fix `GET /api/metrics` `Query(None)` Bug (`backend/api/routers/positions.py:281`):**
   - Stop calling the FastAPI endpoint `get_positions(user_id=user_id)` directly (which bound `active_only` to `Query(None)`!).
   - Extract `_compute_positions_payload(user_id, active_only)` and `_compute_metrics_payload(user_id)` with explicit Python defaults (`active_only: Optional[bool] = None`).
   - `_compute_metrics_payload(user_id)` executes a lightweight SQL query selecting only `(user_ticker, company_name, currency, latest_price, previous_close)` across all instruments for the tenant (respecting `active_only=False` / all instruments, matching SQLite and eliminating unnecessary column/ORM hydration).
2. **Eliminate `pd.read_sql_query` & `df.iterrows()`:**
   - Replace `pd.read_sql_query` + `df.iterrows()` in `positions.py` SQLite branch with `conn.row_factory = sqlite3.Row` and `cursor.fetchall()` direct iteration.
3. **PG `user_positions_view` / Column Projection:**
   - In `MultiTenantWatchlistRepository.get_positions_with_calculations`, replace full `UserInstrument` + `MarketQuote` ORM hydration with a single lightweight SQLAlchemy column-projection `SELECT` (matching exact existing response fields including `quote_provider` and `inst.exchange`/`inst.currency` precedence, or querying `user_positions_view` when `quote_provider` is not needed/joined cleanly), avoiding `created_at`/`updated_at`/`error_message` and ORM identity-map overhead.
4. **Bounded LRU+TTL Caches:**
   - Wrap `_POSITIONS_CACHE` and `_METRICS_CACHE` (`backend/api/routers/positions.py`) in a thread-safe bounded `OrderedDict` helper (`MAX_CACHE_ENTRIES = 256`, `CACHE_TTL_SECONDS = 60.0`) that evicts expired entries and oldest LRU entries when `len > MAX_CACHE_ENTRIES`.
   - Bound `_LAST_KNOWN_QUOTES` (`src/portfoliomaster/db/multi_tenant_repository.py`) with `OrderedDict` and `MAX_DELTA_CACHE_ENTRIES = 2048` (LRU eviction on write).
   - Ensure `refresh_single_instrument` and `create_instrument_endpoint` invalidate cached positions/metrics across affected tenants when a shared `MarketQuote` price/status changes (`invalidate_positions_cache()` on quote mutation; `invalidate_positions_cache(user_id)` on private instrument metadata mutation).

---

## 5. Verification Strategy (Spec-TDD)
- **Red Phase (`tests/test_concurrency_and_query_budget.py`):**
  - `assert_max_queries` context manager using SQLAlchemy `before_cursor_execute` and `sqlite3` `set_trace_callback` to assert exact upper bounds (`<= 8` for `import_or_restore_user_watchlist(N=25)`, `<= 2` for `get_export_records(N=20)` -> `1`, `0` joins for `GET /api/instruments`, `1` `DELETE ... RETURNING` for `DELETE /api/instruments/{ticker}`).
  - Multi-tenant refresh & cooldown isolation tests (`User A` `POST /api/refresh?force=true` leaves `User B` untouched; unchanged prices update `last_attempt_at`; UTC-aware 30s single-instrument cooldown).
  - SSE tests (`GET /api/refresh/stream` does not trigger refresh; `asyncio.Queue(maxsize=100)` handles `QueueFull` safely; tenant A events never reach tenant B; raw exception strings never leak).
  - Thread-safety, pool-isolation (`session_scope()` closed during Yahoo mock execution), and bounded cache (`maxsize=256`) tests.
- **Green & Quality Gate:**
  - Sequential implementation `U4.1` -> `U4.2` -> `U4.3`, keeping 100% of `pytest` passing at each step.
  - Frontend validation (`npm run lint`, `npx tsc --noEmit --incremental false`, `npm test`, `npm run build`) for the surgical SSE caller update.
