# Specification 01: Dependencies, Supply Chain Security, Lockfile & Repository Hygiene (U1)

## 1. Scope
This specification defines the dependency management, supply chain security, lockfile reproducibility, and repository hygiene baseline for **PortfolioMaster** (Unit 1). It explicitly excludes application refactoring (FastAPI routers, database/Alembic schemas, business logic, or React components).

## 2. Python Single Source of Truth & Deterministic Lockfile
- **Single Manifest:** `pyproject.toml` is the sole authoritative manifest for Python dependencies:
  - `[project].dependencies`: runtime dependencies only.
  - `[project.optional-dependencies].dev`: development and test-only dependencies.
- **No Hand-Maintained Duplicates:** Remove manually edited `requirements.txt` and `requirements-dev.txt`.
- **Reproducible Cross-Platform Lockfiles:** Generate deterministic lockfiles from `pyproject.toml` using `uv pip compile --universal`:
  - `requirements.lock`: compiled from `pyproject.toml` (runtime dependencies, compatible with both Windows local `venv` and Linux Render builds).
  - `requirements-dev.lock`: compiled from `pyproject.toml --extra dev` (runtime + dev/test dependencies for local development and verification).
  - Both lockfiles must retain the auto-generated header indicating `pyproject.toml` as source and the exact regeneration command.
- **Direct Import Rule (No Phantom Dependencies):**
  - Every third-party package imported directly in `src/`, `backend/`, `alembic/`, `tests/`, `scripts/`, or `conftest.py` must be explicitly declared in `pyproject.toml`.
  - Verified direct imports retained in runtime `[project].dependencies`: `pandas`, `openpyxl`, `yfinance`, `requests`, `urllib3` (used directly in `src/portfoliomaster/providers/yahoo_adapter.py`), `sqlalchemy`, `alembic`, `psycopg[binary]`, `fastapi`, `pydantic`, `uvicorn[standard]`, `python-multipart`, `python-dotenv`, `pyjwt[crypto]`.
  - Verified dev/test imports/runners in `[project.optional-dependencies].dev`: `pytest`, `pytest-timeout` (used by `pytest.ini`), `httpx`, and `cryptography` (imported directly in `tests/test_auth_security.py`, also pulled by `pyjwt[crypto]`).
  - Unused dependency removed: `pytest-cov` (0 references in `pytest.ini`, tests, scripts, or CI).
- **Deploy & Local Launch Alignment:**
  - `render.yaml` `buildCommand`: `"pip install -r requirements.lock && pip install --no-deps ."` (ensures pinned lockfile installation without re-resolving unpinned bounds).
  - `run.bat`: `pip install -r requirements.lock` when initializing `venv`.
  - `AGENTS.md`: updated minimally with the official lockfile regeneration and installation commands if changed.

## 3. Supply Chain Security Criteria
- **Python (`venv` & `requirements.lock` / `requirements-dev.lock`):**
  - **0 CRITICAL** and **0 HIGH** advisories reported by `pip-audit` against both the installed `venv` and the compiled lockfiles.
  - Known baseline vulnerabilities to remediate via minimum version floors / lockfile resolution:
    - `certifi>=2026.10.18` (resolves CRITICAL `GHSA-6q48-6c7w-9gw2` / `PYSEC-2026-4320`).
    - `soupsieve` and `opentelemetry-api` (or any other transitive package flagged by `pip-audit`) upgraded to patched non-vulnerable versions.
- **Frontend (`frontend/`):**
  - Upgrade `next` and `eslint-config-next` in `frontend/package.json` in lockstep to the latest patched 16.x security release without introducing breaking changes to React 19, TypeScript 5, Tailwind CSS v4, or ESLint 9.
  - Regenerate `frontend/package-lock.json` cleanly with zero peer dependency errors.
  - **0 CRITICAL**, **0 HIGH**, and **0 `next` advisories** in `npm audit`; `next dev` must start cleanly without aborting due to security advisories and serve HTTP 200 on `/`.

## 4. Repository Hygiene & Configuration Cleanup
- **`.gitignore` Hardening:**
  - Ensure all SQLite transient/database files (`*.db`, `*.db-journal`, `*.db-wal`, `*.db-shm`, `*.sqlite*`), local environment files (`.env`, `.env.local`, `*.env`, `.env.*`, with explicit `!.env.example` exception), and ephemeral automation artifacts (`.playwright-cli/`) are ignored.
- **Obsolete Deployment/Environment Variables Audit:**
  - `PORTFOLIOMASTER_ENV`: 0 references across codebase and config; ensure absent from `render.yaml` and `.env.example`.
  - `BATCH_SIZE`: `src/portfoliomaster/core/config.py:70` retains a legacy fallback (`os.getenv("REFRESH_BATCH_SIZE") or os.getenv("BATCH_SIZE")`). In `render.yaml`, `REFRESH_BATCH_SIZE` is already explicitly set to `"50"`, making the duplicate `BATCH_SIZE` entry redundant; remove `BATCH_SIZE` from `render.yaml` while preserving `REFRESH_BATCH_SIZE: "50"` (and without refactoring `config.py`, which is outside U1 scope). `.env.example` already sets `REFRESH_BATCH_SIZE=50` and documents `BATCH_SIZE` only in a comment.
- **Secret & Local Artifact Safety:**
  - Never print, log, or modify secret values in `.env` or `frontend/.env.local`.
  - Clean only purely ephemeral tool cache artifacts (`.playwright-cli/`).
  - Never silently delete `portfolio.db`, `CSV_example.csv`, `backups/`, or `SQL_supabase.txt`; inventory their exact Git tracking/ignore status and byte size in the final report for explicit user approval.

## 5. Verification Matrix
| Target | Command | Pass Criterion |
|---|---|---|
| Python Vulnerabilities | `uvx pip-audit -r requirements.lock` & `uvx pip-audit` (in `venv`) | Exit 0, 0 CRITICAL / 0 HIGH advisories |
| Backend Tests | `.\venv\Scripts\pytest.exe` | 100% pass (baseline 176 passed, 0 failures) |
| Frontend Vulnerabilities | `npm audit` (in `frontend/`) | 0 advisories in `next`, 0 CRITICAL/HIGH |
| Frontend Lint | `npm run lint` (in `frontend/`) | Exit 0, 0 errors |
| Frontend Types | `npx tsc --noEmit --incremental false` (in `frontend/`) | Exit 0, 0 errors |
| Frontend Tests | `npm test` (in `frontend/`) | Exit 0, 100% pass |
| Frontend Build | `npm run build` (in `frontend/`) | Exit 0 |
| Frontend Dev Smoke | `npm run dev` + `GET http://localhost:3000/` then terminate | HTTP 200, no security abort, port 3000 freed |
| Ports Clean | `netstat -ano \| Select-String ":3000\s\|:8000\s"` | Empty output (ports closed) |
