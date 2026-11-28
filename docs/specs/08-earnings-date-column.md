# Specification 08: Next Earnings Date Column (`earnings_date`)

## 1. Scope & Acceptance Criteria
Deliver a read-only **Next Earnings Date (`earnings_date`)** column in `WatchlistTable`, backed end-to-end by market data (`YahooAdapter`), global market persistence (`market_quotes` / SQLite `quotes`), API/SSE propagation, and frontend presentation.

### 1.1 Non-Negotiable Constraints
1. **Data Ownership:** `earnings_date` is global market metadata per ticker (`provider_symbol`), **not** per-user data.
   - Multi-tenant PostgreSQL (`schema.py`): lives on `market_quotes` (`earnings_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)`).
   - Local SQLite (`connection.py` / `repository.py`): lives on `quotes` (`earnings_date DATE`).
2. **Canonical Type & Timezone Safety:** Stored as SQL `DATE` and transported as ISO-8601 `YYYY-MM-DD` string or `null` (`Optional[date]` in Python, `string | null` in TypeScript), identical to `analysis_date`. UI formatting never passes `"YYYY-MM-DD"` through `new Date(...)` (no off-by-one UTC-to-local day shift).
3. **Future-Only Normalization & Null Fallback:** Only upcoming dates `>= today` (UTC date) are retained. Past dates, invalid values (`NaN`, `NaT`, malformed strings), ETFs/indices without earnings, or provider errors normalize to `None` (`null` in JSON), and the UI renders exact text **`N/A`**.
4. **Read-Only UI & Visual Parity:**
   - Not inline-editable (no `<button>` trigger, no date picker, no modal input, no countdown badges, no animations).
   - Reuses the exact `formatStackedDate(isoDate)` helper from `frontend/lib/watchlist-formatters.ts` and the exact two-line stacked typography (`DD/MM` over `YYYY`) of `InlineDateCell` (`analysis_date`).
   - Supports chronological sorting with `null`/`N/A` consistently placed **last** in both ascending and descending sort directions (`sortUndefined: 'last'`).
5. **Scope Boundaries:** Zero redesign of `WatchlistTable`, zero new dependencies in `pyproject.toml` or `frontend/package.json`, zero regression to `.csv`/`.xlsx`/`.json` import/export round-trips, and zero breakage of existing `localStorage` preferences.

---

## 2. Database Schema & Alembic Migration

### 2.1 `src/portfoliomaster/core/models.py` & `src/portfoliomaster/db/schema.py`
- `Quote` dataclass: add `earnings_date: Optional[date] = None`.
- `MarketQuote` ORM model: add `earnings_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)`.

### 2.2 Local SQLite (`src/portfoliomaster/db/connection.py`)
- Add `earnings_date DATE` to `CREATE TABLE IF NOT EXISTS quotes (...)`.
- Add idempotent column migration in `init_db()`: check `PRAGMA table_info(quotes)` and execute `ALTER TABLE quotes ADD COLUMN earnings_date DATE` if absent.

### 2.3 Alembic Migration (`alembic/versions/4d0e5f6a7b8c_add_earnings_date_to_market_quotes.py`)
- `down_revision = '3c9d4e5f6a7b'`.
- **`upgrade()`:**
  - PostgreSQL (`bind.dialect.name == "postgresql"`):
    - `ALTER TABLE public.market_quotes ADD COLUMN IF NOT EXISTS earnings_date DATE`
    - Recreate `public.user_positions_view` (`WITH (security_invoker = true)`) adding `mq.earnings_date`, preserving `REVOKE ALL FROM PUBLIC, anon` and `GRANT SELECT TO authenticated, service_role`.
  - SQLite / non-PostgreSQL:
    - Inspect columns of `market_quotes`; if `market_quotes` exists and `earnings_date` is absent, execute `op.add_column("market_quotes", sa.Column("earnings_date", sa.Date(), nullable=True))`.
- **`downgrade()`:**
  - PostgreSQL:
    - `DROP VIEW IF EXISTS public.user_positions_view`, recreate view without `mq.earnings_date` and re-apply grants.
    - `ALTER TABLE public.market_quotes DROP COLUMN IF EXISTS earnings_date`.
  - SQLite / non-PostgreSQL:
    - Inspect columns of `market_quotes`; if `earnings_date` exists, drop it via `op.batch_alter_table("market_quotes")`.
- **Supabase RLS & Security:** `market_quotes` already grants `SELECT` (`USING (true)`) to `authenticated`, `ALL` to `service_role`, and no privileges to `anon`. No policy changes required; `user_positions_view` preserves `security_invoker = true`.

---

## 3. `YahooAdapter` Extraction, Resiliency & Performance

### 3.1 Extraction & Normalization Rules (`src/portfoliomaster/providers/yahoo_adapter.py`)
Add pure helper `normalize_next_earnings_date(raw_values: Any, *, today: Optional[date] = None) -> Optional[date]` and `_extract_next_earnings_date(ticker: Any, *, today: Optional[date] = None) -> Optional[date]`:
1. **Supported Yahoo Shapes:**
   - Primary (lightweight JSON `calendarEvents`): `ticker.calendar` when it is a `dict` (checking keys `'Earnings Date'`, `'earningsDate'`, `'earnings_date'`) or `pd.DataFrame` (column/row `'Earnings Date'`).
   - Fallback (only when `ticker.calendar` raises an exception or is unavailable — e.g. crumb 401 on cloud IPs — and never interpreting unconfigured `MagicMock` objects): `ticker.get_earnings_dates(limit=8)` when it returns a `pd.DataFrame` with a `DatetimeIndex` / `'Earnings Date'` column.
2. **Candidate Coercion & Strict Future Filter:**
   - Flatten iterables/lists/tuples/Series/Index.
   - Coerce each candidate to `datetime.date` (`pd.Timestamp`, `datetime`, `date`, ISO/string via `parse_date`, or epoch `int`/`float` excluding `bool`/`NaN`/`Inf`).
   - Discard `None`, `NaT`, `NaN`, and any `d < today` (where `today = datetime.now(timezone.utc).date()`).
   - Select `min(future_dates)` (closest upcoming date `>= today`).
3. **Failure Isolation:**
   - All earnings extraction runs inside defensive `try ... except Exception:` blocks. Any network, parsing, rate-limit, or crumb failure resolves cleanly to `None` and **never** degrades or aborts `price`, `previous_close`, `quote_timestamp`, `status`, or raises HTTP 500.

### 3.2 Concurrency & Batch Refresh Latency Guard (`REFRESH_BATCH_SIZE=50`)
- **Bounded In-Memory TTL Cache (`_EARNINGS_CACHE`):**
  - Thread-safe `OrderedDict[str, tuple[Optional[date], float]]` protected by `threading.Lock` (max `2048` entries, default TTL `21600` seconds = 6 hours, configurable via `EARNINGS_CACHE_TTL_SECONDS`).
  - Exposes `clear_earnings_cache(symbols=None)` (invoked in `tests/conftest.py` `test_db_isolation` alongside `clear_quote_delta_cache()`).
  - Eliminates repeated Yahoo `calendar` requests across 150s periodic auto-refreshes while keeping quotes fresh.
- **Bounded Parallel Execution:**
  - In `YahooAdapter.fetch(symbols)`, after batch `yf.download` + `missing_symbols` fallback, any `unique_yahoo_symbols` with a cache miss on earnings are fetched concurrently via `ThreadPoolExecutor(max_workers=min(8, len(uncached)))`, reusing already-created `yf.Ticker` instances from the fallback step whenever available.
  - Exposes `YahooAdapter.fetch_next_earnings_date(self, symbol: str) -> Optional[date]` for clean unit testing and direct lookups.

---

## 4. Persistence, API & SSE Contracts

### 4.1 Persistence Parity (`PortfolioStore`, `SqliteWatchlistStore`, `PostgresWatchlistStore`)
- **Non-destructive Upsert Semantics:**
  - If incoming `Quote.earnings_date` is a valid `date`, persist it.
  - If incoming `Quote` is `ERROR`/`UNAVAILABLE` (`price is None`), preserve existing stored `earnings_date`.
  - If incoming `Quote` has a valid price and `earnings_date is None`: clear stored `earnings_date` if it is already `< today`, and preserve a still-future stored `earnings_date >= today` (protects against transient `calendar` 401/429 glitches).
- **Delta Cache (`multi_tenant_repository.py`):**
  - `filter_unchanged_quotes` compares `(price, previous_close, status, earnings_date)` so newly resolved or changed `earnings_date` values are never skipped.
- **Serialization:**
  - `quote_to_dict(quote)` includes `"earnings_date": earnings_dt.isoformat() if earnings_dt else None`.
  - `get_positions()` in both `SqliteWatchlistStore` and `PostgresWatchlistStore` emits `"earnings_date": str | None` (`YYYY-MM-DD` or `None`).
  - `save_single_refresh_result` and `get_single_refresh_target` include `"earnings_date"` in the `"quote"` summary dict.

### 4.2 SSE Delta Payload & Cache Invalidation (`backend/api/services/refresh_coordinator.py`)
- In `execute_refresh_all` (`on_batch`), `quotes_delta_payload[sym]` emits:
  ```json
  {
    "price": 210.5,
    "previous_close": 208.0,
    "status": "FRESH",
    "quote_timestamp": "2026-11-28T15:00:00+00:00",
    "earnings_date": "2027-01-28"
  }
  ```
- `/api/positions` cache (`ETag`) continues to be invalidated by `invalidate_positions_cache()` on batch/single refresh and instrument mutations.

---

## 5. Frontend UI, Sorting, i18n & Storage Compatibility

### 5.1 Types & Live SSE Context (`frontend/lib/types.ts`, `frontend/context/PortfolioRefreshContext.tsx`)
- `Position`, `Quote`, and `RefreshProgressEvent['quotes'][sym]` add `earnings_date?: string | null;`.
- `PortfolioRefreshContext` updates `earnings_date` in-place when `'earnings_date' in quote` on incoming SSE `batch` frames.

### 5.2 Shared Date Formatting & Chronological Sorting (`frontend/lib/watchlist-formatters.ts`)
- Reuse `formatStackedDate(isoDate)` directly (zero duplicate date parser).
- Add pure helpers:
  - `normalizeIsoDateForSort(isoDate: string | null | undefined): string | undefined` — returns trimmed `YYYY-MM-DD` if valid, otherwise `undefined` (so `@tanstack/react-table` `sortUndefined: 'last'` places `null`, `undefined`, `""`, and invalid strings consistently last in both ascending and descending order).
  - `compareIsoDates(a: string | null | undefined, b: string | null | undefined): number` — pure chronological comparator (`YYYY-MM-DD` lexicographic comparison matches calendar order).
- Column width budget (`DEFAULT_WATCHLIST_COLUMN_WIDTHS`, total `<= 1180px` for `1280x800` desktop):
  - Add `earnings_date: 90` and rebalance sibling columns slightly while keeping `decline_to_target >= 95`, `target_price >= 85`, `actions >= 55`, and total sum `<= 1180px`:
    - `analysis_date: 78`, `user_ticker: 98`, `company_name: 132`, `exchange: 74`, `currency: 58`, `latest_price: 94`, `daily_variation: 88`, `ytd_variation: 88`, `variation_since_analysis: 96`, `decline_to_target: 96`, `target_price: 86`, `earnings_date: 90`, `actions: 82` -> **Total = `1160px <= 1180px`**.

### 5.3 Column Definition (`frontend/components/watchlist/watchlistColumns.tsx`)
- Placed right after `target_price` (immediately before `actions`).
- Read-only cell:
  - Calls `formatStackedDate(row.original.earnings_date)`.
  - When valid: renders stacked `dayMonth` (`text-xs font-semibold text-zinc-200 font-mono tabular-nums leading-tight`) and `year` (`text-[10px] text-zinc-500 font-mono tabular-nums leading-none mt-0.5`).
  - When `null`/invalid: renders exact `N/A` in `text-zinc-500 font-mono text-xs tabular-nums`.
- Header: clickable sort button with `ColumnSortIndicator`, localized 2-line label (`colEarnings` + `colDate` / `colEarningsSub`) and `sortByEarningsDate` title.
- Sorting: `accessorFn: (row) => normalizeIsoDateForSort(row.earnings_date)`, `id: 'earnings_date'`, `sortUndefined: 'last'`, `sortingFn: (rowA, rowB, columnId) => compareIsoDates(rowA.getValue(columnId), rowB.getValue(columnId))`.

### 5.4 i18n (`frontend/lib/translations.ts`)
Add symmetric keys to `enTranslations` and `esTranslations`:
- `colEarnings`: `'Earnings'` / `'Próx.'`
- `colEarningsDate`: `'Date'` / `'Resultados'`
- `sortByEarningsDate`: `'Sort by next earnings date'` / `'Ordenar por fecha de próximos resultados'`

---

## 6. Explicit Blast-Radius Analysis

| Area | Impact & Risk | Mitigation / Verification |
|---|---|---|
| **Alembic & `test_alembic_and_schema.py`** | Existing test `test_alembic_single_head_and_offline_sql_hardening` asserts `head_rev.down_revision == "2a8b9c0d1e2f"`. | Update assertion to chain `2a8b9c0d1e2f -> 3c9d4e5f6a7b -> 4d0e5f6a7b8c`; verify offline SQL upgrade/downgrade and SQLite round-trip. |
| **PostgreSQL `user_positions_view`** | Recreating view with `mq.earnings_date` must preserve `security_invoker = true` and `REVOKE ALL FROM PUBLIC, anon`. | Explicitly execute `CREATE OR REPLACE VIEW ... WITH (security_invoker = true)` + `REVOKE`/`GRANT` in upgrade and revert cleanly in downgrade. |
| **Delta Filter (`filter_unchanged_quotes`)** | Existing cache tuple `(price, prev_close, status)` would skip DB writes if only `earnings_date` changed. | Include `earnings_date` in cached comparison tuple; verify in unit test. |
| **`YahooAdapter` & `MagicMock` tests** | Bare `MagicMock()` tickers return `MagicMock` for `.calendar` / `.get_earnings_dates`, which could cause crashes or false values. | Strictly type-check `isinstance(cal, (dict, pd.DataFrame))` and `isinstance(df, pd.DataFrame)`; clear `_EARNINGS_CACHE` in `conftest.py`. |
| **Import/Export Round-Trip (`.csv`, `.xlsx`, `.json`)** | `export_to_excel` hardcodes column alignment indices (`col_idx in (1, 3, ...)`). | Leave `EXPORT_COLUMNS` unchanged (global live market metadata is not user-imported input); include optional `earnings_date` in `get_export_records()` / JSON `_quote` only, preserving 100% round-trip parity. |
| **Frontend `localStorage` (`columnSizing` & `sorting`)** | Existing users have saved `columnSizing` maps lacking `earnings_date`. | `@tanstack/react-table` automatically falls back to `columnDef.size` (`90px`) for any column absent from `columnSizing`; existing saved widths/sort states remain valid without hydration errors. |
| **Frontend `DEFAULT_WATCHLIST_COLUMN_WIDTHS` Budget** | `test_table_ssr_and_budget.mts` and `test_u7_modular_units.mts` enforce `sum <= 1180px`, `decline_to_target >= 95`, `target_price >= 85`, `actions >= 55`. | Rebalanced 13-column sum is `1160px <= 1180px` with all per-column floors satisfied. |
