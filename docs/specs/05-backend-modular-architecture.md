# Specification 05: Backend Modular Architecture, Unified Persistence & Test Consolidation (U5)

## 1. Scope & Non-Negotiable Invariants
- **In Scope (U5):**
  - Centralize safe parsing in `src/portfoliomaster/core/parsing.py` (`U5.1`).
  - Consolidate Yahoo historical/analysis/YTD fetching inside `YahooAdapter` and eliminate `sys.modules["backend.api.main"]` via FastAPI dependency injection (`U5.1`).
  - Introduce a unified persistence `Protocol` and dialect adapters (`SqliteWatchlistStore` + `PostgresWatchlistStore`) resolved through FastAPI DI (`U5.2`).
  - Extract cohesive domain services and SSE broker (`backend/api/services/`), reducing `instruments.py`, `refresh.py`, `positions.py`, `import_export.py`, `backup.py`, and `config.py` to thin HTTP routers with zero direct `is_multi_tenant_db()` CRUD/query branching (`U5.3`).
  - Consolidate `tests/` and `backend/tests/` into `tests/{unit,integration,security}/` with shared fixtures (`tests/conftest.py`), zero duplicate tests, updated `pytest.ini`, and updated `AGENTS.md` (`U5.4`).
- **Out of Scope & Invariants (U1–U4, U6–U7):**
  - **Zero** changes to `pyproject.toml`, lockfiles, `schema.py`, Alembic migrations, or `frontend/` (`git diff -- frontend/` MUST remain empty).
  - Preserve **100%** of OpenAPI routes, HTTP methods, response contracts, and U3 security rules.
  - Preserve **100%** of U4 concurrency and query optimizations: zero Yahoo HTTP calls inside `session_scope()`, zero duplicate `session.commit()`, `asyncio.to_thread` in background loop / `import/preview`, `threading.local()` in `YahooAdapter`, `Lock` on JWKS/engine/state, `asyncio.Queue(maxsize=100)` tenant-filtered SSE, UTC-aware `last_attempt_at`, `noload`, `DELETE ... RETURNING`, O(1) batch import/restore, and bounded LRU+TTL caches.

---

## 2. Sub-unit U5.1: Canonical Parsing & Unified `YahooAdapter`

### 2.1 `src/portfoliomaster/core/parsing.py`
Pure, stateless parsing utilities replacing all scattered copies across `calculations.py`, `multi_tenant_repository.py`, `repository.py`, `yahoo_adapter.py`, `exporters.py`, `import_session.py`, `common.py`, `instruments.py`, and `import_export.py`:
- `parse_decimal(value: Any, *, positive_only: bool = False, allow_zero: bool = True) -> Optional[Decimal]`:
  - Supports `Decimal`, `int`, `float`, and strings in both EU (`"1.147,21"`) and US (`"1,147.21"`) formats, stripping whitespace and `%`.
  - Rejects `bool`, `NaN`, `Inf`, and invalid strings (returning `None`).
  - Enforces `> 0` when `positive_only=True` or `>= 0` when `allow_zero=False` is combined.
- `parse_positive_decimal(value: Any) -> Optional[Decimal]`: shorthand for `parse_decimal(value, positive_only=True)`.
- `parse_date(value: Any) -> Optional[date]`:
  - Handles `None`, NaN/NaT/blank strings, `datetime` (converted cleanly via `.date()`), `date`, ISO-8601 strings (`YYYY-MM-DD` or `YYYY-MM-DD[T ]...`), and common import formats (`%d/%m/%Y`, `%d-%m-%Y`, `%d/%m/%y`, `%Y/%m/%d`).
- `parse_optional_iso_date(raw: Optional[str], field_name: str) -> Optional[date]`:
  - Strict ISO-8601 parser that raises `ValueError(f"Invalid ISO date format for '{field_name}': expected YYYY-MM-DD")` on malformed strings (mapped to HTTP 422 in routers/services).
- `parse_datetime(value: Any) -> Optional[datetime]`:
  - Parses `datetime`, `date`, ISO-8601, and `%Y-%m-%d %H:%M:%S` strings.
- `parse_bool(value: Any, *, default: bool = True, empty_as_false: bool = False) -> bool`:
  - Unified truthy/falsy parser (`true/1/yes/y/si/sí/s` vs `false/0/no/n/f/off`), supporting blank-string semantics explicitly via `empty_as_false` / `default`.
- `clean_str(value: Any) -> str`, `clean_opt_str(value: Any) -> Optional[str]`, `safe_float(value: Any) -> Optional[float]`, `positive_float(value: Any, *, ndigits: int = 4) -> Optional[float]`.

### 2.2 `YahooAdapter` & Dependency Seam (`backend/api/dependencies.py`)
- Move historical and start-of-year lookup logic (`fetch_start_of_year_quote`, `fetch_historical_quote_and_date`, `fetch_historical_quote_for_date`, and `resolve_company_name`) into `YahooAdapter` (`src/portfoliomaster/providers/yahoo_adapter.py`), preserving `threading.local()` resilient sessions, UTC-aware timestamps, and eliminating `hist.iterrows()` in historical close extraction.
- Create `backend/api/dependencies.py` providing `get_yahoo_provider() -> YahooAdapter` (overridable via `app.dependency_overrides[get_yahoo_provider]` in tests) and remove all `sys.modules.get("backend.api.main")` dynamic lookups and `backend/api/main.py` re-exports.

---

## 3. Sub-unit U5.2: Unified Persistence Layer (`PortfolioStore` Protocol & Adapters)

### 3.1 `src/portfoliomaster/db/ports.py`
Define `PortfolioStore` (`typing.Protocol`) as a **deep module** whose methods encapsulate short, self-contained DB transactions (never spanning network I/O):
- `supports_sqlite_file_backups: bool` (capability flag: `True` for SQLite, `False` for multi-tenant Postgres).
- **Instruments CRUD & Queries:**
  - `count_active_instruments() -> int` (global count for scheduler).
  - `list_instruments(active_only: bool = True) -> List[dict]` (PG uses `noload(UserInstrument.quote)`).
  - `get_instrument_detail(ticker: str) -> Optional[tuple[dict, Optional[dict]]]`.
  - `instrument_exists(ticker: str) -> bool`.
  - `create_instrument(payload: dict, fetched_quote: Optional[Quote], manual_price: Optional[float]) -> tuple[dict, Optional[dict]]`.
  - `update_instrument(ticker: str, fields_set: set[str], updates: dict) -> dict` (raises `KeyError` when missing, `ValueError` on duplicate rename).
  - `delete_instrument(ticker: str) -> bool` (PG uses single `DELETE ... RETURNING id`).
- **Reference Price Persistence (3-Phase Safe):**
  - `get_analysis_lookup_target(ticker: str) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]`
  - `save_analysis_price(target_id: Any, price: Decimal, actual_date: date) -> None`
  - `get_ytd_lookup_target(ticker: str) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]`
  - `save_ytd_price(target_id: Any, price: Decimal, actual_date: date) -> None`
  - `list_missing_analysis_candidates() -> tuple[int, List[tuple[Any, str, date]], int]`
  - `save_missing_analysis_prices(resolved: List[tuple[Any, Decimal, date]]) -> None`
  - `list_missing_ytd_candidates() -> tuple[int, List[tuple[Any, str]], int]`
  - `save_missing_ytd_prices(resolved: List[tuple[Any, Decimal, date]]) -> None`
- **Positions & Metrics:**
  - `get_positions(active_only: bool = False) -> List[dict]`
  - `get_metrics_rows() -> List[tuple[str, str, str, Optional[float], Optional[float]]]`
- **Import, Export & Backup:**
  - `import_watchlist(items: List[dict], replace_all: bool = False) -> int` (PG: O(1) batch; SQLite: single-tx `upsert_instruments_batch`).
  - `export_records() -> List[dict]` (PG: column projection; SQLite: 1-query `LEFT JOIN`).
  - `wipe_all() -> None`
- **Refresh Coordination:**
  - `check_and_prepare_batch_refresh(now_utc: datetime, force: bool, stale_seconds: int) -> dict` (returns status `in_progress`/`fresh`/`empty`/`ready`, `run_id`, `stale_symbols`, `symbol_counts`, `symbol_currencies`, `existing_quote_symbols`, `total_symbols`).
  - `persist_refresh_batch(run_id: Any, chunk_quotes: Dict[str, Quote], symbol_counts: Dict[str, int], symbol_currencies: Dict[str, str], existing_quote_symbols: set[str], processed_count: int, updated: int, failed: int) -> tuple[int, int, int, int]`
  - `complete_refresh_run(run_id: Any, status: str, diagnostic_summary: Optional[str] = None, error_message: Optional[str] = None) -> None`
  - `get_active_refresh_run() -> Optional[dict]`
  - `get_single_refresh_target(ticker: str, now_utc: datetime, force: bool, single_cooldown_seconds: int) -> Optional[dict]`
  - `save_single_refresh_result(target: dict, fetched_quote: Quote, resolved_analysis_price: Optional[Decimal], resolved_soy_price: Optional[Decimal], resolved_soy_date: Optional[date]) -> dict`
  - `list_active_symbols() -> frozenset[str]`

### 3.2 Concrete Adapters & DI Wiring
- `SqliteWatchlistStore` (`src/portfoliomaster/db/repository.py`): implements `PortfolioStore` over SQLite using existing `repository.py` functions (`upsert_instruments_batch`, `get_all_instruments_with_quotes`, etc.) and `sqlite3.Row` iteration.
- `PostgresWatchlistStore` (`src/portfoliomaster/db/multi_tenant_repository.py`): implements `PortfolioStore` scoped to `user_id` (or `None` for background scheduler) delegating to `MultiTenantWatchlistRepository`, `GlobalMarketQuotesRepository`, and `RefreshRunRepository` inside short `db_session.session_scope()` blocks.
- `backend/api/dependencies.py`:
  - `get_portfolio_store(user_id: uuid.UUID = Depends(get_current_user_id)) -> PortfolioStore`
  - `get_system_portfolio_store() -> PortfolioStore` (for background scheduler & `GET /api/config`)
  - Single central `is_multi_tenant_db()` selection inside `dependencies.py` (and auth config check in `common.py`).

---

## 4. Sub-unit U5.3: Domain Services & Thin Routers

| Module | Responsibility | Target Size |
|---|---|---|
| `backend/api/services/instrument_service.py` | CRUD orchestration, `check-yahoo`, 3-phase `fetch-analysis-price` / `fetch-ytd-price` / parallel `resolve-missing-*`, post-commit cache invalidation | ~260 lines |
| `backend/api/services/refresh_sse.py` | `_SSESubscriber`, bounded `asyncio.Queue(maxsize=100)`, `_state` + `_state_lock`, tenant-filtered broadcast, async SSE generator | ~180 lines |
| `backend/api/services/refresh_coordinator.py` | Per-user/global locks, 3-phase `execute_refresh_all`, `refresh_single_instrument`, `BatchRunner` outside DB sessions, auto-resolve analysis/YTD | ~240 lines |
| `backend/api/services/import_export_service.py` | `_parse_import_bytes`, `confirm_import`, shared `export_watchlist_payload` (CSV/Excel/JSON + backup download) | ~160 lines |
| `backend/api/routers/instruments.py` | Thin HTTP router (`Depends(get_portfolio_store)`, `Depends(get_yahoo_provider)`) | <= 320 lines |
| `backend/api/routers/refresh.py` | Thin HTTP router (`POST /api/refresh`, `GET /api/refresh/stream`, `POST /api/instruments/{ticker}/refresh`) | <= 180 lines |
| `backend/api/routers/positions.py` | Bounded LRU+TTL cache + ETag/304 + `store.get_positions` / `store.get_metrics_rows` | <= 200 lines |
| `backend/api/routers/import_export.py` | Thin HTTP router for preview/confirm/exports | <= 140 lines |
| `backend/api/routers/backup.py` | Thin HTTP router using `store` + capability flag `store.supports_sqlite_file_backups` | <= 180 lines |
| `backend/api/routers/config.py` | Read-only `/health*` + `/api/config` backed by `get_system_portfolio_store()` | <= 85 lines |

---

## 5. Sub-unit U5.4: Test Consolidation Matrix (`tests/{unit,integration,security}/`)

All 27 legacy files across `tests/` (23) and `backend/tests/` (4) consolidate into `tests/` (`pytest.ini`: `testpaths = tests`), removing `backend/tests/` with zero loss of unique assertions:

| Target File | Source Files Consolidated | Exact Merges / Deduplication |
|---|---|---|
| `tests/conftest.py` | `tests/conftest.py` + shared fixtures | Clean `isolated_sqlite_db`, `isolated_mt_env`, `mint_jwt`, `override_yahoo_provider` fixtures (no module-level DB side effects) |
| `tests/unit/test_parsing.py` | New U5.1 suite | EU/US decimals, `NaN`/`Inf`, dates, booleans, `clean_str` |
| `tests/unit/test_calculations.py` | `tests/test_calculations.py` | Pure financial calculations |
| `tests/unit/test_ingest.py` | `tests/test_ingest.py` | CSV parsing, ES column map, duplicate detection, `normalize()` |
| `tests/unit/test_yahoo_adapter.py` | `tests/test_providers.py`, `tests/test_refresh_functionality.py` (normalizer/suffix), `backend/tests/test_api.py` (`_fetch_historical_quote_and_date`), U5.1 seam tests | Merge duplicate `normalize()` checks with `test_ingest.py`; add `YahooAdapter` historical/YTD + `threading.local()` tests |
| `tests/unit/test_refresh_pipeline.py` | `tests/test_batch_runner.py`, `tests/test_phase3_provider_refresh_api.py` (dedup), `tests/test_quote_delta_and_upsert.py` (delta filter) | Pure `BatchRunner` & `_LAST_KNOWN_QUOTES` delta logic |
| `tests/unit/test_idle_activity.py` | `backend/tests/test_idle_refresh.py` | Idle tracker + middleware filtering |
| `tests/integration/test_repository_contract.py` | `tests/test_db.py`, `tests/test_multitenant_data_layer.py`, `tests/test_phase3_provider_refresh_api.py` (repo), `tests/test_quote_delta_and_upsert.py` (batch upsert), `tests/test_regression_fixes_parity.py` (SQLite repo), new U5.2 parity tests | Merge duplicate `upsert_market_quotes_batch` test; parametrize `PortfolioStore` contract over SQLite & PG |
| `tests/integration/test_alembic_and_schema.py` | `tests/test_alembic_precedence_and_db_session.py`, `tests/test_schema_and_alembic_parity.py`, `tests/test_migration_script.py` (idempotent upgrade) | Merge duplicate Alembic upgrade checks; preserve 100% of U2 RLS/schema/URL precedence tests |
| `tests/integration/test_migration_script.py` | `tests/test_migration_script.py` | SQLite -> Postgres migration script tests |
| `tests/integration/test_api_sqlite.py` | `backend/tests/test_api.py` (HTTP/CRUD/import/YTD), `tests/test_route_bugs_parity.py` | Uses fixture DB + `dependency_overrides`; preserves 100% of endpoint behavior |
| `tests/integration/test_api_contracts.py` | `tests/test_u3_contracts_and_security.py` (HTTP contracts), new U5 OpenAPI & zero-`is_multi_tenant_db`-in-routers tests | Preserves U3 POST/PUT/check-yahoo/GET contracts + verifies 28 OpenAPI routes intact |
| `tests/integration/test_backup_and_export.py` | `tests/test_backup.py`, `backend/tests/test_backup_api.py`, `tests/test_regression_fixes_parity.py` (export/restore) | Consolidated backup/restore/CSV/Excel/JSON round-trips |
| `tests/integration/test_positions_cache.py` | `backend/tests/test_positions_cache.py` | ETag/304 + cache invalidation (replaces dummy unused import with real `/api/refresh` invalidation check) |
| `tests/integration/test_refresh_api.py` | `tests/test_refresh_cooldown.py`, `tests/test_refresh_stream_sync.py`, `tests/test_refresh_coordination_and_cors.py` (RefreshRun/SSE), `tests/test_refresh_functionality.py` (mock/network) | Fix stale-run cleanup & SSE tests; keep `@pytest.mark.network` test |
| `tests/integration/test_concurrency_and_query_budget.py` | `tests/test_concurrency_and_query_budget.py`, `tests/test_backend_hardening.py` (pool/async) | All U4 query budgets, session lifetimes, UTC cooldowns, SSE tenant isolation, bounded caches |
| `tests/security/test_auth_and_isolation.py` | `tests/test_auth_security.py`, `tests/test_backend_hardening.py` (JWT/headers), `tests/test_refresh_coordination_and_cors.py` (CORS) | Auth 401/403, JWKS, HSTS, CORS validation |
| `tests/security/test_input_bounds_and_safety.py` | `tests/test_backup_safety_regression.py`, `tests/test_u3_contracts_and_security.py` (error masking, role, formula injection, XLSX/upload/restore bounds) | Deduplicate overlapping invalid-decimal & formula-sanitization cases while keeping every edge input |
