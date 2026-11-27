# Specification 03: Dead Code Removal, HTTP/TS Contracts & Backend Security Hardening (U3)

## 1. Scope & Boundaries
- **In Scope (U3):** Verified dead-code deletion in `src/portfoliomaster/` (and exclusive legacy test cleanup/migration), security hardening (error masking in production, JWT claim & issuer enforcement, formula injection sanitization, streaming upload & row limits, removing `NEXT_PUBLIC_API_URL`), multi-tenant `MarketQuote` isolation on `POST`/`PUT /api/instruments`, and canonical HTTP/Pydantic/TypeScript contract alignment.
- **Out of Scope (U4–U7):** Do NOT optimize event-loop/`asyncio.to_thread`/`threading.local()`/JWKS locking/`session_scope()` outside Yahoo/double `commit()`/cooldown `last_attempt_at`/SSE `force=true`/N+1 import-restore (U4); do NOT split `instruments.py`/`refresh.py` monoliths or unify `is_multi_tenant_db()` branches (U5); do NOT alter UI layout, CSS, i18n, or a11y in React components (U6/U7). Frontend edits are restricted strictly to `frontend/lib/api.ts`, `frontend/lib/types.ts`, `frontend/next.config.ts`, `frontend/app/api/[...path]/route.ts`, and minimal contract/type fixes required by `tsc` (and `frontend/scripts/verify_api_client.mts` if needed).

---

## 2. Sub-unit U3.1: Verified Dead Code Removal & Preservation Contract

### 2.1 Symbols & Files Deleted
1. `src/portfoliomaster/refresh/service.py` (`RefreshService`, `_refresh_lock`, `is_locked`, `refresh_unique_symbols`, `execute_global_refresh_uow`) and its export in `src/portfoliomaster/refresh/__init__.py`.
2. `UnitOfWork`, `GlobalMarketQuotesRepository.save_quote_success`, `GlobalMarketQuotesRepository.save_quote_failure`, `GlobalMarketQuotesRepository.get_quotes_batch`, and `MultiTenantWatchlistRepository.get_instrument_by_id` in `src/portfoliomaster/db/multi_tenant_repository.py`.
3. `get_db_session` and `create_all_tables` in `src/portfoliomaster/db/session.py`.
4. `YahooAdapter.fetch_historical_quote`, `_orig_get_crumb_basic`, `_orig_get_crumb_csrf` in `src/portfoliomaster/providers/yahoo_adapter.py`, plus unused `.batch_supported` and `.default_batch_size` properties across `providers/base.py`, `providers/yahoo_adapter.py`, and `providers/mock_provider.py`.
5. `is_target_reached` in `src/portfoliomaster/core/calculations.py` (and write-only `target_valid` field assignment in `decline_to_target`).
6. Dead model methods/dataclasses in `src/portfoliomaster/core/models.py`: `QuoteStatus.is_usable_for_alerts`, `QuoteStatus.display_label`, `_STATUS_DISPLAY_LABELS`, `QuoteStatus.is_fresh`, `Quote.is_fresh`, `Instrument.display_ticker`, `CalculationResult.summary`, `CalculationResult.target_reached`, `CalculationResult.target_reached_valid`, `CalculationResult.target_valid`, `RefreshRun` (dataclass), `FreshnessConfig.freshness_state`, `ImportSummary`.
7. Unused constants in `src/portfoliomaster/core/config.py`: `DEFAULT_DELAY_SECONDS`, `DEFAULT_STALENESS_SECONDS`, `MAX_BATCH_SIZE`, `MAX_RETRIES`, `BASE_BACKOFF_SECONDS`, `MAX_BACKOFF_SECONDS`, `DEFAULT_BIND_ADDRESS`, `DEFAULT_PORT`, `EXCHANGE_CURRENCY`.

### 2.2 Explicitly Preserved Symbols
- `GlobalMarketQuotesRepository.upsert_market_quote_safe` (wired into `POST /api/instruments` in U3.3 and `refresh.py`).
- `GlobalMarketQuotesRepository.get_quote` (active read helper used by tests).
- `RefreshRunRepository.can_user_refresh` (reserved for U4 per-tenant cooldown).
- `MockProvider` (`src/portfoliomaster/providers/mock_provider.py`, used by active tests in `tests/test_providers.py` and `tests/test_refresh_functionality.py`).
- `POST /api/instruments/resolve-missing-analysis-prices` & `POST /api/instruments/resolve-missing-ytd-prices` (called directly by `backend/api/routers/refresh.py` in SQLite mode and tested by `backend/tests/test_api.py`; frontend has 0 callers for `frontend/lib/api.ts` helpers, left intact for U4/U5).
- All Alembic, `scripts/migrate_sqlite_to_web.py`, and backend test hooks (`GUID`, `Base`, `utc_now`, `_fetch_historical_quote_for_date`, etc.).

### 2.3 Legacy Test Migration
- Remove tests that exclusively cover deleted dead symbols (`test_is_target_reached`, `test_historical_quote_does_not_falsely_fallback_for_old_dates`, `test_historical_quote_returns_observation_within_lookback_window`, `test_refresh_service_global_refresh_flow`, `test_quote_failure_preserves_last_valid_price`).
- Migrate live-repository tests (`test_tenant_isolation_coexistence_and_queries`, `test_case_insensitive_ticker_search`, `test_shared_market_quotes_decoupling`, `test_tristate_patch_field_clearing`, `test_import_or_restore_user_watchlist_parity`) from `UnitOfWork`/`save_quote_success` to `MultiTenantWatchlistRepository` and `GlobalMarketQuotesRepository.upsert_market_quote_safe`.

---

## 3. Sub-unit U3.2: Security Hardening & Input Bounds

### 3.1 Production Error Sanitization
- **`backend/api/main.py` (`unhandled_exception_handler`):** Use `is_production()` (aligned with `db/session.py`, covering `ENVIRONMENT=production/prod`, `RENDER=true`, `NODE_ENV=production`). When `is_production()` is True, **never** expose `{exc}` on `IntegrityError`/`CheckViolation`/`NotNullViolation` or any 500 error — return `"Database constraint violation."` or `"An unexpected internal error occurred on the server."` while logging the exception server-side.
- **`backend/api/routers/backup.py`:** Catch `(ValueError, InvalidOperation)` on `validate_json_backup_payload` and `restore_from_json` (preventing 500s on invalid decimals). In production, never include raw `{e}` in HTTP error details (`Invalid JSON format`, `Error restoring backup`, SQLite validation failure).
- **`backend/api/routers/import_export.py`:** Mask raw DB/parser exceptions in production (`Database error during import.`, generic parse/commit failure messages).
- **`backend/api/common.py` (`get_current_user`):** Never return raw `({e})` in 401 details (`DecodeError`, `PyJWKClientError`, `PyJWTError`, `get_unverified_header` errors); log server-side and return static safe messages.
- **`backend/api/routers/refresh.py` & `config.py`:** In production, `_execute_refresh_all` sets `_state["last_refresh_result"] = "error: Refresh failed"` (never leaking `{e}` via public `GET /api/config`, SSE, or `POST /api/refresh` responses).

### 3.2 JWT Authentication Hardening (`backend/api/common.py`)
- **Explicit Role Enforcement:** Replace `payload.get("role", "authenticated")` with `payload.get("role")` and require `role == "authenticated"` explicitly (reject missing role or `service_role` with HTTP `403`).
- **Issuer & `SUPABASE_URL` Enforcement:**
  - When `SUPABASE_URL` is configured, strictly verify `iss == f"{clean_supabase_url}/auth/v1"`.
  - In production (`is_production()`) multi-tenant deployments, `validate_auth_configuration()` and `get_current_user()` MUST require `SUPABASE_URL` to be set (fail closed with `500` if missing, preventing silent `verify_iss=False` degradation). In non-production test environments (`not is_production()`), HS256 test tokens remain usable when `SUPABASE_URL` is unset.

### 3.3 Export Formula Injection Hardening (`src/portfoliomaster/backup/exporters.py`)
- `_sanitize_formula(val)`: Neutralize any string starting with `=`, `+`, `-`, `@`, `\t`, `\r`, `\n`, **or starting with any leading whitespace/control characters followed by `=`, `+`, `-`, `@`** by prefixing `'`. Numeric `int`/`float` cells in Excel and `float` values in CSV continue serializing as numbers without `'`.

### 3.4 Streaming Upload & Row Bounds
- **`backend/api/routers/import_export.py` (`POST /api/import/preview`):** Read uploaded `UploadFile` in `65536`-byte chunks, aborting immediately with HTTP `413` if total bytes exceed `MAX_UPLOAD_BYTES` (`5 MB`), without relying on `content-length` or buffering unbounded payloads in memory.
- **`src/portfoliomaster/ingest/parser.py`:** Enforce `max_rows: int = 2000` (`MAX_IMPORT_ROWS`) during parsing:
  - XLSX (`openpyxl` `read_only=True`): iterate at most `max_rows + 1` data rows (`itertools.islice`), returning `(None, error)` cleanly before materializing a DataFrame if exceeded.
  - CSV (`pd.read_csv`): pass `nrows=max_rows + 1`, returning `(None, error)` cleanly if `len(df) > max_rows`.
- **`backend/api/routers/backup.py` & `exporters.py` (`validate_json_backup_payload`):** Enforce maximum `500` instruments in JSON backup payloads **before** executing any database writes or `replace_all` deletes (returning HTTP `400`).
- **`backend/api/routers/import_export.py` (`POST /api/import/confirm`):** In SQLite mode, when `committed == 0` and `commit_errors` is non-empty, return HTTP `400` (`detail={"message": "...", "errors": commit_errors}`) instead of silent `200 OK`; when `committed > 0` and `commit_errors` is non-empty, return `200` with `status="partial"` and `errors=commit_errors`.

### 3.5 Frontend Internal URL Protection
- Remove `NEXT_PUBLIC_API_URL` from `frontend/lib/api.ts`, `frontend/next.config.ts`, and `frontend/app/api/[...path]/route.ts`. Server-side SSR/BFF uses `API_BASE_URL` (or `BACKEND_URL`), and browser code uses relative `/api/...` routes only so no internal backend URL is ever inlined into client bundles.

---

## 4. Sub-unit U3.3: Multi-Tenant Integrity & Canonical HTTP/TS Contracts

### 4.1 `POST /api/instruments` (Multi-Tenant Integrity & Parity)
- **Strict Date Validation:** Invalid ISO strings in `analysis_date` or `start_of_year_date` return HTTP `422 Unprocessable Entity` (eliminate silent `except ValueError: pass`).
- **Safe `MarketQuote` Persistence:** Use `GlobalMarketQuotesRepository(session).upsert_market_quote_safe(...)` when a Yahoo quote is fetched so failed/empty Yahoo responses never overwrite existing valid `MarketQuote.price` or `last_valid_fetched_at`.
- **`manual_price` Tenant Isolation:** In multi-tenant PostgreSQL mode, **never** mutate shared `MarketQuote.price`, `previous_close`, or `status` with a tenant-provided `manual_price` / `manual_previous_close`. Keep `MarketQuote` placeholder untouched (only `ON CONFLICT DO NOTHING` via `create_instrument`) and return `quote={"source": "manual", "price": manual_price}` in the `POST` response (consistent with U2's shared `market_quotes` schema and preserving isolation across tenants).
- **Historical Analysis Price Parity:** When `analysis_date` is provided without `analysis_reference_price` and `fetch_yahoo=True`, resolve historical price via `_fetch_historical_quote_and_date(provider_symbol, analysis_dt, window_days=10)` in multi-tenant mode as well (and use `ref_year = analysis_dt.year if analysis_dt else date.today().year` for YTD lookup).

### 4.2 `PUT /api/instruments/{ticker}` (Multi-Tenant & SQLite Parity)
- **Schema Alignment:** Add `active?: boolean | null` to TypeScript `InstrumentUpdateRequest` (`frontend/lib/types.ts`).
- **`provider_symbol` Synchronization:** Recompute `provider_symbol` (and `exchange` when `"AUTO"` / currency-driven) whenever `new_ticker`, `exchange`, or `currency` is in `fields_set` (in both multi-tenant and SQLite branches), and include `"provider_symbol"` in the `fields_set` passed to `MultiTenantWatchlistRepository.update_instrument(...)`. Ensure a placeholder `MarketQuote` row exists for the updated `provider_symbol`.
- **Explicit `company_name` Clearing:** When `"company_name"` is in `fields_set` and the value is `""` or `None`, persist `None` (`NULL`) in multi-tenant mode (`update_instrument` removes the `company_name is not None` guard).
- **Strict Date Validation:** Invalid `analysis_date` or `start_of_year_date` strings return HTTP `422`.
- **`latest_price` / `previous_close` Isolation:** In multi-tenant mode, do not mutate shared `MarketQuote` from `PUT` `latest_price`/`previous_close`.

### 4.3 `GET /api/instruments/check-yahoo` Canonical Contract
- **No Redundant Calls:** Call `resolve_company_name(symbol, t)` at most once and reuse `_get_exchange_metadata()` output.
- **Canonical Pydantic Model (`CheckYahooResponse` in `backend/api/schemas.py`) & TS Alignment:**
  - Fields: `status: str`, `available: bool`, `valid: bool`, `ticker: str`, `provider_symbol: str`, `exchange: str`, `currency: str`, `price: Optional[float] = None`, `previous_close: Optional[float] = None`, `company_name: Optional[str] = None`, `message: Optional[str] = None`, `error: Optional[str] = None`.
  - Populate `previous_close` from `fast_info` / `meta` / `history` when available, and populate both `message` and `error` with a descriptive status string when unavailable.
  - **Upstream Error Status:** Return HTTP `502 Bad Gateway` (with sanitized `detail` in production) on external Yahoo/network failure instead of `200 OK`.

### 4.4 `GET /api/instruments/{ticker}` Canonical Contract
- Consolidate response payload to canonical `{"instrument": inst_dict, "quote": quote_dict}` (removing duplicated top-level `**inst_dict` keys).
- Align `InstrumentDetailResponse` in `frontend/lib/types.ts` (`instrument: Instrument`, `quote: Quote | null`, and `Instrument.id: number | string`) and update the existing test assertions (`tests/test_auth_security.py`, `tests/test_route_bugs_parity.py`) to read `response.json()["instrument"]`.
