# Specification 02: Database Schema, Alembic Alignment, Supabase RLS, Triggers, Constraints & Indexes (U2)

## 1. Single Source of Truth & Scope
- **Authoritative Schema Sources:** `src/portfoliomaster/db/schema.py` (SQLAlchemy declarative models) and the chained `alembic/versions/` history (`1756f565959b` -> `2a8b9c0d1e2f` -> `3c9d4e5f6a7b`).
- **Legacy Reference:** `local/SQL_supabase.txt` is strictly non-authoritative historical reference and must not be modified or deleted in U2.
- **Immutability Rule:** Already-applied migrations `1756f565959b` and `2a8b9c0d1e2f` must **not** be edited. All U2 PostgreSQL/Alembic changes are delivered via a new idempotent incremental revision chained from `down_revision = '2a8b9c0d1e2f'`.
- **Production Safety Rule:** Never execute `alembic upgrade`, `alembic downgrade`, or any DDL/DML against the production Supabase database in `.env`. Verify migrations offline (`alembic upgrade head --sql`, `alembic downgrade ... --sql`) and via isolated SQLite tests.

---

## 2. Canonical Table Definitions, Types & Nullability

### 2.1 Numeric Precision (`NUMERIC(20, 6)`)
All 5 financial price columns are standardized to `Numeric(20, 6)` in `schema.py` and `NUMERIC(20, 6)` in PostgreSQL:
- `market_quotes.price`
- `market_quotes.previous_close`
- `user_instruments.analysis_reference_price`
- `user_instruments.start_of_year_price`
- `user_instruments.target_price`

**PostgreSQL Migration Ordering Guard:** Because `public.user_positions_view` depends on these columns, PostgreSQL rejects `ALTER COLUMN ... TYPE NUMERIC(20, 6)` while the view exists. The migration MUST execute `DROP VIEW IF EXISTS public.user_positions_view;` before altering column types, and recreate the view afterward.

### 2.2 Nullability & Column Type Alignment
- `user_instruments.company_name`: `String(255)`, `nullable=True` (`DROP NOT NULL` in migration to reconcile `1756f565959b`'s `NOT NULL` with `schema.py` and `local/SQL_supabase.txt`, safely allowing explicit clearing in U3 without breaking existing rows).
- `user_instruments.comment`: `Text`, `nullable=True` (`DROP NOT NULL` in migration to reconcile `1756f565959b`'s `NOT NULL` with `schema.py` and `local/SQL_supabase.txt`).
- `market_quotes.status`: `SQLEnum(..., length=20, native_enum=False, create_type=False)` with `server_default="UNAVAILABLE"` in `schema.py` so compiled DDL matches `VARCHAR(20)` in `1756f565959b` / `2a8b9c0d1e2f` / `local/SQL_supabase.txt`.

---

## 3. `CHECK` Constraints & Blast-Radius Rationale

### 3.1 Constraints Enforced in Both `schema.py` and PostgreSQL Migration
| Table | Constraint Name | Expression | Blast-Radius Check |
|---|---|---|---|
| `market_quotes` | `chk_market_quotes_price_pos` | `price IS NULL OR price > 0` | Safe; valid quotes always have positive price. |
| `market_quotes` | `chk_market_quotes_prev_close_pos` | `previous_close IS NULL OR previous_close > 0` | Safe; `previous_close` is nullable when unavailable. |
| `market_quotes` | `chk_market_quotes_status` | `status IN ('FRESH', 'DELAYED', 'STALE', 'UNAVAILABLE', 'ERROR')` | Matches `QuoteStatus` enum and `local/SQL_supabase.txt`. |
| `user_instruments` | `chk_user_instruments_analysis_price_pos` | `analysis_reference_price IS NULL OR analysis_reference_price > 0` | Validated by repository `_parse_dec`. |
| `user_instruments` | `chk_user_instruments_soy_price_pos` | `start_of_year_price IS NULL OR start_of_year_price > 0` | Validated by repository `_parse_dec`. |
| `user_instruments` | `chk_user_instruments_target_price_pos` | `target_price IS NULL OR target_price > 0` | Validated by repository `_parse_dec`. |
| `user_instruments` | `chk_user_ticker_length` | `length(trim(user_ticker)) >= 1 AND length(trim(user_ticker)) <= 50` | Matches `String(50)` and works in both SQLite and PostgreSQL. |
| `refresh_runs` | `chk_refresh_runs_status` | `status IN ('RUNNING', 'COMPLETED', 'FAILED', 'TIMEOUT', 'PARTIAL')` | Includes `'PARTIAL'` used by `tests/test_multitenant_data_layer.py`. |
| `refresh_runs` | `chk_counts_nonneg` | `total_symbols >= 0 AND processed_symbols >= 0 AND failed_symbols >= 0 AND successful_symbols >= 0` | Matches `RefreshRunRepository`. |
| `refresh_runs` | `chk_completed_after_start` | `completed_at IS NULL OR completed_at >= started_at` | Matches `RefreshRun` lifecycle. |

### 3.2 PostgreSQL-Only Symbol Regex Constraints (Widened for Blast-Radius)
- `chk_market_quotes_symbol_format`: `provider_symbol ~ '^[A-Z0-9._\-^=/&]{1,50}$'`
- `chk_provider_symbol_format`: `provider_symbol IS NULL OR provider_symbol ~ '^[A-Z0-9._\-^=/&]{1,50}$'`
- **Blast-Radius Adjustment:** Widened from `local/SQL_supabase.txt`'s `[A-Z0-9.\-^=/]{1,30}` to permit `_` (used by existing parity/security tests such as `SAN_TEST`, `AAPL_TEST`, `AAPL_ATTACK`), `&` (e.g., `AT&T`), and up to 50 chars matching `String(50)`.

### 3.3 Legacy `SQL_supabase.txt` Constraints Intentionally Excluded
- `chk_analysis_price_has_date` and `chk_soy_price_has_date` are **excluded** (and dropped if present from legacy `SQL_supabase.txt`) because `PUT /api/instruments/{ticker}` (`test_tristate_patch_field_clearing`) allows clearing `analysis_date` to `NULL` independently of `analysis_reference_price`.

---

## 4. Index Matrix (Canonical vs. Redundant Removal)

### 4.1 Redundant Indexes Removed (in `schema.py` and via `DROP INDEX IF EXISTS`)
| Index | Table | Reason Removed |
|---|---|---|
| `ix_refresh_runs_status` | `refresh_runs` | Covered by leftmost prefix of `idx_refresh_runs_active (status, started_at)`. |
| `ix_refresh_runs_user_id` | `refresh_runs` | Covered by leftmost prefix of `idx_refresh_runs_user_started (user_id, started_at)`. |
| `ix_user_instruments_user_id` | `user_instruments` | Covered by leftmost prefix of `uq_user_instruments_tenant_ticker (user_id, user_ticker)`, `idx_user_instruments_tenant_active (user_id, active)`, and `idx_user_instruments_user_upper_ticker`. |

Also drop legacy duplicate `idx_user_instruments_user_ticker_ci` if present from `local/SQL_supabase.txt` so `(user_id, upper(user_ticker))` has one canonical unique index (`idx_user_instruments_user_upper_ticker`).

### 4.2 Retained & Added Canonical Indexes
| Table | Index / Constraint | Definition | Purpose |
|---|---|---|---|
| `market_quotes` | `idx_market_quotes_status_attempt` | `(status, last_attempt_at)` | Stale/error quote batch scheduling. |
| `market_quotes` | `idx_market_quotes_last_attempt` | `(last_attempt_at)` | Freshness ordering. |
| `user_instruments` | `uq_user_instruments_tenant_ticker` | `UNIQUE (user_id, user_ticker)` | Tenant ticker uniqueness. |
| `user_instruments` | `idx_user_instruments_user_upper_ticker` | `UNIQUE (user_id, upper(user_ticker))` | Case-insensitive lookup (`func.upper(user_ticker)` in `multi_tenant_repository.py`); created with `CREATE UNIQUE INDEX IF NOT EXISTS` in migration. |
| `user_instruments` | `idx_user_instruments_tenant_active` | `(user_id, active)` | Active watchlist filtering per tenant. |
| `user_instruments` | `ix_user_instruments_active` | `(active)` | Global active instrument scans for background refresh. |
| `user_instruments` | `ix_user_instruments_provider_symbol` | `(provider_symbol)` | Reverse lookup / quote joins. |
| `refresh_runs` | `idx_refresh_runs_user_started` | `(user_id, started_at)` | Per-user cooldown & history queries. |
| `refresh_runs` | `idx_refresh_runs_active` | `(status, started_at)` | Global/active run concurrency lock queries. |

---

## 5. Supabase RLS & Privilege Matrix

Forensic audit confirms `frontend/` never queries Postgres/PostgREST directly (Auth-only `@supabase/ssr` + FastAPI BFF) and FastAPI connects as DB owner (`DATABASE_URL`). Because `NEXT_PUBLIC_SUPABASE_URL` and anon/publishable keys are public, RLS must still strictly defend PostgREST endpoints.

| Object | `anon` | `authenticated` | `service_role` |
|---|---|---|---|
| `public.user_instruments` | No access (`REVOKE ALL`) | `SELECT`, `INSERT`, `UPDATE`, `DELETE` where `(select auth.uid()) = user_id` (`UPDATE` has both `USING` and `WITH CHECK`) | Full access |
| `public.market_quotes` | No access (`REVOKE ALL`) | `SELECT` only (`USING (true)`); `INSERT/UPDATE/DELETE` revoked | Full access |
| `public.refresh_runs` | No access (`REVOKE ALL`) | **`SELECT` only** where `user_id = (select auth.uid())`; **`INSERT/UPDATE/DELETE` revoked** and **`user_id IS NULL` global rows strictly hidden/blocked** | Full access |
| `public.user_positions_view` | No access (`REVOKE ALL`) | `SELECT` only (`WITH (security_invoker = true)`, inherits caller RLS on underlying tables) | `SELECT` |

**Critical Remediation:** The migration explicitly drops legacy permissive policies from `local/SQL_supabase.txt` (`"Authenticated users read relevant refresh runs"`, `"Authenticated users insert refresh runs"`, `"Authenticated users update refresh runs"`) so no `authenticated` policy can ever read, insert, or update `refresh_runs` rows with `user_id IS NULL`.

---

## 6. View & Trigger Functions (PostgreSQL Migration)
- **`public.user_positions_view`:** Recreated via `CREATE OR REPLACE VIEW public.user_positions_view WITH (security_invoker = true) AS ...` joining `public.user_instruments` and `public.market_quotes`, with `REVOKE ALL FROM PUBLIC, anon` and `GRANT SELECT TO authenticated, service_role`.
- **`public.set_updated_at()`:** `RETURNS TRIGGER`, `LANGUAGE plpgsql`, `SECURITY INVOKER`, `SET search_path = ''`, `REVOKE ALL FROM PUBLIC, anon, authenticated`. Attached via `trg_user_instruments_updated_at` and `trg_refresh_runs_updated_at` (`BEFORE UPDATE`).
- **`public.ensure_market_quote_placeholder()`:** `RETURNS TRIGGER`, `LANGUAGE plpgsql`, `SECURITY DEFINER`, `SET search_path = ''`, `REVOKE ALL FROM PUBLIC, anon, authenticated`. All table references fully schema-qualified (`public.user_instruments`, `public.market_quotes`). Enforces `provider_symbol ~ '^[A-Z0-9._\-^=/&]{1,50}$'`, 500-instrument per-user cap on `INSERT`, and placeholder `INSERT ... ON CONFLICT (provider_symbol) DO NOTHING`. Attached via `trg_ensure_market_quote` (`BEFORE INSERT OR UPDATE OF provider_symbol`).

---

## 7. Alembic `env.py`, Idempotency & Downgrade Contract
- **`alembic/env.py`:**
  - `run_migrations_offline()` enables `compare_type=True` (matching `run_migrations_online()`) and registers a lightweight offline inspector for `MockConnection` so `alembic upgrade head --sql` succeeds cleanly from revision `None` without modifying immutable `1756f565959b`.
- **Idempotency:** Every DDL block in the new migration uses `DROP ... IF EXISTS`, `CREATE ... IF NOT EXISTS`, `CREATE OR REPLACE`, or `DO $$ BEGIN IF NOT EXISTS (...) ... END IF; END $$;` so it succeeds identically on both a fresh `1756f565959b -> 2a8b9c0d1e2f` database and a Supabase database previously initialized with `local/SQL_supabase.txt`. All PostgreSQL-specific statements (`RLS`, `VIEW`, `FUNCTION`, `TRIGGER`, `DO $$`, `ALTER COLUMN TYPE`) are guarded by `if bind.dialect.name == "postgresql":`.
- **`downgrade()`:** Cleanly and idempotently reverts policies, grants, `user_positions_view`, triggers/functions, `CHECK` constraints, `idx_user_instruments_user_upper_ticker`, `Numeric(18, 6)` precision, `NOT NULL` on `company_name`/`comment` (if safe), and restores the 3 removed indexes back to revision `2a8b9c0d1e2f`.

---

## 8. Safe Manual Production Deployment Checklist (Supabase)
1. Take a full logical/snapshot backup (`pg_dump` or Supabase Dashboard backup).
2. Inspect `SELECT version_num FROM public.alembic_version;` in Supabase SQL Editor.
   - If the DB was initialized manually via `local/SQL_supabase.txt` and has no `alembic_version` row yet, run `alembic stamp 2a8b9c0d1e2f` first (never re-run `1756f565959b`).
3. Verify existing production data against `CHECK` bounds (`price <= 0`, `user_ticker` length) before running `upgrade`.
4. Generate and inspect the offline SQL (`alembic upgrade 2a8b9c0d1e2f:head --sql`).
5. Apply `alembic upgrade head` against production with operator approval and verify `alembic current` and Supabase Advisors.
