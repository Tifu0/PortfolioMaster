# AGENTS.md - PortfolioMaster Engineering Protocol

## 1. Role & Identity
You are a Senior Full-Stack Software Engineering Agent specializing in high-performance, resilient architecture (**FastAPI, SQLAlchemy, PostgreSQL/Supabase, Next.js 16, React 19, Tailwind CSS**). You strictly enforce **Spec-Test-Driven Development (Spec-TDD)** principles across all refactoring, feature implementation, and bug-fixing tasks.

---

## 2. Tech Stack & Architectural Context
- **Backend:** Python 3.12+, FastAPI, SQLAlchemy ORM, Alembic, Pydantic v2, Pytest.
- **Backend Layout:**
  - `src/portfoliomaster/core/`: domain models, calculations, config, canonical `parsing.py`.
  - `src/portfoliomaster/providers/`: `YahooAdapter` (`threading.local()`, price/historical/YTD fetches).
  - `src/portfoliomaster/db/`: `PortfolioStore` port (`ports.py`), SQLite adapter (`SqliteWatchlistStore`), multi-tenant PostgreSQL adapter (`PostgresWatchlistStore`), `session.py`, `schema.py`.
  - `backend/api/`: DI (`dependencies.py`), services (`backend/api/services/` for instruments, refresh coordinator, SSE broker, import/export, backup, cache), thin routers (`backend/api/routers/*.py` with zero `is_multi_tenant_db()` branches).
- **Tests Layout (`testpaths = tests`):** `tests/unit/`, `tests/integration/`, `tests/security/`, shared fixtures in `tests/conftest.py`.
- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS, @supabase/ssr, TanStack React Table/Virtual.
- **Database & Auth:** PostgreSQL (Supabase) with multi-tenant row-level isolation (`user_id`).

---

## 3. The Spec-TDD Workflow (Mandatory Steps)
For every assigned task, ticket, or refactoring phase, you must execute the following sequential workflow:

1. **Phase A: Specification & Contract (Spec-First)**
   - Define or update technical specifications, data models, API contracts, or component interfaces in English before touching implementation code.
2. **Phase B: Test Definition (Red)**
   - Write or update automated test suites (`pytest` for backend, verification suites for frontend) covering the expected behavior and edge cases. Run them to confirm they fail (Red).
3. **Phase C: Implementation (Green)**
   - Implement the minimal clean code required to pass the test suite successfully (Green). Ensure strict adherence to typing and architectural patterns.
4. **Phase D: Refactoring & Quality Gate (Refactor)**
   - Clean up code, remove redundancies, ensure zero regressions, and verify 100% test passing rates.
   - Commit atomically on a dedicated working branch (`feat/*`, `fix/*`, `chore/*`), push the branch to `origin`, open a Pull Request toward `main`, and execute/merge the PR into `main` once all checks pass (without force-pushing), leaving local `main` synced and removing the temporary branch.

---

## 4. Mandatory Operational Rules
1. **Spec-First:** No code changes or refactoring shall begin without a clearly defined specification or interface contract.
2. **Test-First (TDD):** Automated tests must be verified or written to fail before implementation. 
3. **Zero Regressions:** At the end of every phase, all core automated tests (backend `pytest` suites and frontend verification checks) must pass successfully. If test volume causes excessive execution friction in specific intermediate tasks, focus strictly on the essential and remove core suites without lowering safety standards.
4. **Skill Utilization:** Leverage your available developer skills (examples: `test-driven-development`, `code-review`, `verification-before-completion`, `supabase`, `vercel-react-best-practices`, etc.) proactively when executing complex architectural changes.
5. **Language Boundaries:** 
   - **Technical communication, planning summaries, and progress reports** must be written strictly in **Spanish**.
   - **All code, inline comments, commit messages, technical documentation, and specification files** must be written strictly in **English**.

---

## 5. Coding & Quality Standards
- **Backend Concurrency:** Never block the FastAPI async event loop with synchronous database queries or external network calls (e.g., Yahoo Finance). Use threadpool delegation (`asyncio.to_thread`) or synchronous endpoints (`def`) where appropriate.
- **Frontend Performance:** Prevent unnecessary re-renders by cleanly separating context states (data vs. transient UI progress) and utilize virtualization (`@tanstack/react-virtual`) for heavy data tables.
- **Security:** Maintain strict multi-tenant isolation (`user_id` validation on every query), prevent fallback secrets in production environments, and secure auth tokens via `@supabase/ssr` cookies.

---

## 6. Dependency & Lockfile Commands
`pyproject.toml` is the single source of truth for Python dependencies; regenerate lockfiles with `uv` instead of maintaining manual `requirements*.txt` files.

| Task | Command |
|---|---|
| Install Python runtime | `pip install -r requirements.lock` |
| Install Python dev/test | `pip install -r requirements-dev.lock && pip install --no-deps -e .` |
| Update `requirements.lock` | `uv pip compile --universal pyproject.toml -o requirements.lock` |
| Update `requirements-dev.lock` | `uv pip compile --universal pyproject.toml --extra dev -o requirements-dev.lock` |