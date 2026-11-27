# Unit 3 (U3): Dead Code Removal, Contracts & Backend Security Implementation Plan

> **For agentic workers:** Execute Phase B (Red tests) and Phase C (`U3.1` -> `U3.2` -> `U3.3`) sequentially in the coordinator to avoid conflicting edits on `instruments.py` and `multi_tenant_repository.py`.

**Goal:** Delete verified dead code in `src/`, harden backend/frontend security boundaries, isolate shared `MarketQuote` against tenant manual overrides, and align HTTP/Pydantic/TypeScript contracts.

**Architecture:** Three sequential verifiable sub-units (`U3.1` dead code + test migration, `U3.2` security + upload/parser/export bounds + BFF URL hygiene, `U3.3` `POST`/`PUT`/`GET`/`check-yahoo` multi-tenant integrity & contract alignment), followed by SAST (`semgrep`) and full backend + frontend verification.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, PyJWT, Next.js 16, TypeScript 5, Semgrep.

**Spec:** `docs/specs/03-deadcode-contracts-and-security.md`

## Global Constraints
- Strictly stay within U3 scope (no U4 concurrency/cooldown/N+1 work, no U5 router splitting, no U6/U7 UI/CSS changes).
- Never touch `.env` secrets or execute DDL/DML against production Supabase.
- Keep all code, comments, specs, plans, and commit messages in English; report to user in Spanish.
- Do NOT push or auto-merge on `chore`/`fix` branch unless explicitly instructed (`SIN git push ni merge automático`).

---

### Task 1 (Phase B — Red): Security, Bounds & Contract Alignment Tests
**Files:**
- Create: `tests/test_u3_contracts_and_security.py`

- [ ] **Step 1:** Write failing Red tests covering:
  1. `unhandled_exception_handler` in `ENVIRONMENT=production` / `NODE_ENV=production` masks raw `IntegrityError` / exception strings.
  2. `get_current_user` rejects JWT missing `"role"` claim (`403`), masks internal `DecodeError`/`PyJWKClientError` details, and `validate_auth_configuration` / `get_current_user` enforces `SUPABASE_URL` when `ENVIRONMENT=production`.
  3. `_sanitize_formula` neutralizes `=`, `+`, `-`, `@`, `\t`, `\r`, `\n`, and leading whitespace + formula (`"  =SUM(A1)"`, `"\t+1"`).
  4. `POST /api/import/preview` aborts oversized uploads via chunked read (`413`) and `parse_spreadsheet` enforces `MAX_IMPORT_ROWS` (`2000`) during XLSX/CSV parsing; `POST /api/backup/restore` rejects >500 JSON instruments and `InvalidOperation` decimals with `400` (not `500`); `POST /api/import/confirm` returns `400` when `committed == 0` and errors exist.
  5. `POST /api/instruments` (multi-tenant) uses `upsert_market_quote_safe` (never clears valid `MarketQuote` on Yahoo failure), isolates `manual_price` from shared `MarketQuote`, returns `422` on invalid dates, and resolves `analysis_reference_price` when `analysis_date` is set with `fetch_yahoo=True`.
  6. `PUT /api/instruments/{ticker}` (multi-tenant) updates `provider_symbol` on ticker/exchange/currency changes, clears `company_name` explicitly when `""` or `None` is sent, and rejects invalid dates with `422`.
  7. `GET /api/instruments/check-yahoo` calls `resolve_company_name` at most once, populates `available`, `message`, and `previous_close`, and returns `502` on upstream failure; `GET /api/instruments/{ticker}` returns canonical `{"instrument": ..., "quote": ...}` without duplicated top-level instrument keys.
  8. `frontend/lib/api.ts` and `frontend/next.config.ts` contain zero references to `NEXT_PUBLIC_API_URL`.
- [ ] **Step 2:** Run `.\venv\Scripts\pytest.exe tests/test_u3_contracts_and_security.py` and confirm RED failures.

### Task 2 (U3.1): Dead Code Removal & Legacy Test Cleanup
**Files:**
- Delete: `src/portfoliomaster/refresh/service.py`
- Modify: `src/portfoliomaster/refresh/__init__.py`, `src/portfoliomaster/db/multi_tenant_repository.py`, `src/portfoliomaster/db/session.py`, `src/portfoliomaster/providers/base.py`, `src/portfoliomaster/providers/yahoo_adapter.py`, `src/portfoliomaster/providers/mock_provider.py`, `src/portfoliomaster/core/calculations.py`, `src/portfoliomaster/core/models.py`, `src/portfoliomaster/core/config.py`
- Modify tests: `tests/test_calculations.py`, `tests/test_multitenant_data_layer.py`, `tests/test_phase3_provider_refresh_api.py`

- [ ] **Step 1:** Remove verified dead symbols/files while keeping `upsert_market_quote_safe`, `can_user_refresh`, `MockProvider`, and all live/Alembic/script symbols intact.
- [ ] **Step 2:** Remove exclusive dead-code tests and migrate live-repo tests off `UnitOfWork` / `save_quote_success`.
- [ ] **Step 3:** Run full existing `pytest` suite (excluding new U3 Red tests) -> 100% pass.

### Task 3 (U3.2): Security Hardening & Input/URL Bounds
**Files:**
- Modify: `backend/api/main.py`, `backend/api/common.py`, `backend/api/routers/backup.py`, `backend/api/routers/import_export.py`, `backend/api/routers/refresh.py`, `src/portfoliomaster/backup/exporters.py`, `src/portfoliomaster/ingest/parser.py`, `frontend/lib/api.ts`, `frontend/next.config.ts`, `frontend/app/api/[...path]/route.ts`, `tests/test_backend_hardening.py`, `frontend/scripts/verify_api_client.mts`

- [ ] **Step 1:** Implement production error masking, JWT `role == "authenticated"` & prod `SUPABASE_URL` checks, hardened `_sanitize_formula`, chunked preview upload + XLSX/CSV row caps + 500-item JSON restore cap + `InvalidOperation` handling, `import/confirm` error contract, and remove `NEXT_PUBLIC_API_URL`.
- [ ] **Step 2:** Update `bearer()` in `tests/test_backend_hardening.py` and JWT fixture in `frontend/scripts/verify_api_client.mts` to include `"role": "authenticated"`.
- [ ] **Step 3:** Verify security tests pass and `frontend` lint/tsc/test pass.

### Task 4 (U3.3): Multi-Tenant `MarketQuote` Integrity & HTTP/TS Contracts
**Files:**
- Modify: `backend/api/schemas.py`, `backend/api/routers/instruments.py`, `src/portfoliomaster/db/multi_tenant_repository.py`, `frontend/lib/types.ts`, `frontend/lib/api.ts`, `frontend/components/ManualEntryModal.tsx` (minimal contract alignment only), `tests/test_auth_security.py`, `tests/test_route_bugs_parity.py`

- [ ] **Step 1:** Implement `CheckYahooResponse`, single `resolve_company_name`, `previous_close` + `message` + `502` on upstream failure, canonical `GET /api/instruments/{ticker}`, safe `POST /api/instruments` (`upsert_market_quote_safe`, `manual_price` isolation, `422` dates, `analysis_reference_price` parity), and `PUT /api/instruments/{ticker}` (`provider_symbol` sync, `company_name` clear, `422` dates, `active` TS contract).
- [ ] **Step 2:** Run `tests/test_u3_contracts_and_security.py` + full `pytest` + frontend `lint`, `tsc`, `npm test`, `npm run build` -> 100% GREEN.

### Task 5 (Phase D): SAST (`semgrep`), Code Review, Verification & Atomic Commits
- [ ] **Step 1:** Run `semgrep` (`--metrics=off`) over modified files and verify 0 findings; perform `code-review` & `find-bugs` on full `git diff`.
- [ ] **Step 2:** Re-verify full `pytest`, `npm run lint`, `tsc --noEmit`, `npm test`, `npm run build`.
- [ ] **Step 3:** Create atomic conventional commits on `fix/u3-deadcode-contracts-security` (without `git push` or merge).
