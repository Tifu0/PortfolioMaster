# Unit 2 (U2): Alembic, Schema, Supabase RLS & Indexes Implementation Plan

> **For agentic workers:** Execute Phase B (Red test) and Phase C (U2.1 -> U2.2 -> U2.3) sequentially in the coordinator to avoid schema/Alembic drift.

**Goal:** Eliminate drift between `schema.py`, Alembic migrations, and `local/SQL_supabase.txt`; fix the `refresh_runs` `user_id IS NULL` RLS vulnerability; add view, triggers, safe `CHECK` constraints, `Numeric(20, 6)`, and functional index; and drop 3 redundant indexes.

**Architecture:** `schema.py` + chained `alembic/versions/` (`1756f565959b` -> `2a8b9c0d1e2f` -> new U2 revision) become the single authoritative schema source. All verification runs offline (`--sql`) and on isolated SQLite DBs without touching `.env` production Supabase.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, PostgreSQL/Supabase RLS, Pytest.

**Spec:** `docs/specs/02-database-schema-and-rls.md`

## Global Constraints
- NEVER run `alembic upgrade`/`downgrade` or DDL/DML against `.env` production `DATABASE_URL`.
- NEVER print `.env` secrets or delete `local/SQL_supabase.txt`.
- NEVER edit `1756f565959b_initial_multi_tenant_schema_with_.py` or `2a8b9c0d1e2f_add_server_default_to_market_quotes_status.py`.
- Keep all code, comments, specs, plans, and commits in English; report to user in Spanish.

---

### Task 1 (Phase B — Red): Parity, Index Hygiene & Offline SQL Security Tests
**Files:**
- Create: `tests/test_schema_and_alembic_parity.py`

- [ ] **Step 1:** Write tests asserting:
  1. `schema.py` uses `Numeric(20, 6)` for all 5 price columns, `nullable=True` for `user_instruments.company_name` and `comment`, `VARCHAR(20)` for `market_quotes.status`, expected `CheckConstraint`s, `idx_user_instruments_user_upper_ticker`, and **zero** redundant indexes (`ix_refresh_runs_status`, `ix_refresh_runs_user_id`, `ix_user_instruments_user_id`).
  2. Alembic has exactly 1 `head` chained cleanly from `1756f565959b` -> `2a8b9c0d1e2f` -> U2 head.
  3. Offline `alembic upgrade head --sql` (PostgreSQL URL) succeeds without error, drops the 3 redundant indexes (`DROP INDEX IF EXISTS`), creates `idx_user_instruments_user_upper_ticker`, sets `NUMERIC(20, 6)`, recreates `user_positions_view` with `security_invoker = true` after `DROP VIEW IF EXISTS` and after `ALTER COLUMN`, creates `set_updated_at` and `ensure_market_quote_placeholder` with `SET search_path = ''`, enables RLS on all 3 tables, defines `(select auth.uid())` policies, drops insecure `refresh_runs` policies, and contains **no** `authenticated` policy granting `INSERT`/`UPDATE`/`SELECT` on `user_id IS NULL`.
  4. Offline `alembic downgrade 2a8b9c0d1e2f --sql` succeeds cleanly.
- [ ] **Step 2:** Run `.\venv\Scripts\pytest.exe tests/test_schema_and_alembic_parity.py` and confirm RED failure.

### Task 2 (U2.1): Align `src/portfoliomaster/db/schema.py` & `alembic/env.py`
**Files:**
- Modify: `src/portfoliomaster/db/schema.py`
- Modify: `alembic/env.py`

- [ ] **Step 1:** Update `schema.py` (`Numeric(20, 6)`, `SQLEnum(..., length=20)`, `CheckConstraint`s per spec, remove `index=True` from `UserInstrument.user_id`, `RefreshRun.user_id`, `RefreshRun.status`).
- [ ] **Step 2:** Update `alembic/env.py` (`compare_type=True` in `run_migrations_offline()`, offline `MockConnection` inspection fallback so `alembic upgrade head --sql` passes without modifying `1756f565959b`).
- [ ] **Step 3:** Run existing `pytest` suite (`-k "not parity"`) to confirm SQLite & existing tests remain green.

### Task 3 (U2.2): Create Idempotent Incremental Alembic Migration
**Files:**
- Create: `alembic/versions/3c9d4e5f6a7b_align_schema_rls_triggers_view_and_indexes.py`

- [ ] **Step 1:** Implement `upgrade()` (`down_revision = '2a8b9c0d1e2f'`) following exact PostgreSQL dependency order: drop view -> drop redundant/legacy constraints & indexes -> alter column types/nullability -> create functional index & `CHECK` constraints -> create `SET search_path = ''` functions & triggers -> recreate `user_positions_view` (`security_invoker = true`) & grants -> harden RLS policies & privileges.
- [ ] **Step 2:** Implement symmetric idempotent `downgrade()` back to `2a8b9c0d1e2f`.
- [ ] **Step 3:** Inspect full offline SQL from `alembic upgrade head --sql` and `alembic downgrade 2a8b9c0d1e2f --sql`.

### Task 4 (U2.3 & Phase D): Green Verification, Review, Commits & PR
- [ ] **Step 1:** Run `pytest tests/test_schema_and_alembic_parity.py` (GREEN) and full `pytest` suite (100% pass).
- [ ] **Step 2:** Run `code-review` & `blast-radius` verification over diff and offline SQL.
- [ ] **Step 3:** Create 4 atomic commits on `fix/u2-alembic-rls-alignment`, push to `origin`, and open PR toward `main`.
