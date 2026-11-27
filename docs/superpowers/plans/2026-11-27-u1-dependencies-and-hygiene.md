# Unit 1 (U1): Dependencies, Supply Chain & Repository Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `dispatching-parallel-agents` (swarm lanes `@u1-python-supply-chain` and `@u1-frontend-next-sec`) for U1.1 and U1.2, then converge in coordinator for U1.3 and Phase D.

**Goal:** Establish a single source of truth for Python dependencies with cross-platform deterministic lockfiles, remediate Python and Next.js supply chain advisories, harden `.gitignore`, and clean obsolete deployment config without touching application business logic.

**Architecture:** `pyproject.toml` becomes the sole Python dependency manifest compiled via `uv pip compile --universal` into `requirements.lock` and `requirements-dev.lock`, consumed by `render.yaml`, `run.bat`, and local `venv`. Frontend upgrades `next` and `eslint-config-next` in lockstep via npm while preserving React 19 / ESLint 9 / Tailwind v4 compatibility.

**Tech Stack:** Python 3.12, `uv`, `pip`, `pip-audit`, `pytest`, Next.js 16, React 19, TypeScript 5, ESLint 9, Tailwind CSS v4.

**Spec:** `docs/specs/01-dependencies-and-hygiene.md`

## Global Constraints
- Strictly stay within U1 scope: no refactoring of routers, DB/Alembic, business logic, or React components.
- Never print or modify secret values in `.env` or `frontend/.env.local`.
- Never delete `portfolio.db`, `CSV_example.csv`, `backups/`, or `SQL_supabase.txt`.
- Keep all code, comments, specs, plans, and commit messages in English; report to user in Spanish.

## Review Focus
- Cross-platform lockfile compatibility: `requirements.lock` generated on Windows must remain valid on Linux Render (`--universal`).
- `render.yaml` build command must install from `requirements.lock` and run `pip install --no-deps .` so `pip install .` does not override pinned versions.
- Direct imports (`requests`, `urllib3`, `cryptography`) must stay explicitly declared in `pyproject.toml`.
- `next` and `eslint-config-next` versions must match identically to avoid ESLint/Next plugin mismatches.
- `next dev` smoke test process tree must be cleanly terminated so port 3000 is free afterward.

---

### Task 1 (U1.1): Python Supply Chain, Lockfile & Render Alignment (`@u1-python-supply-chain`)

**Files:**
- Modify: `pyproject.toml`
- Create: `requirements.lock`, `requirements-dev.lock`
- Delete: `requirements.txt`, `requirements-dev.txt`
- Modify: `render.yaml` (buildCommand only in U1.1, or coordinate with U1.3 so no file conflict: U1.1 owns `pyproject.toml`, `requirements*`, `run.bat`, and `render.yaml` `buildCommand`; U1.3 handles `BATCH_SIZE` in `render.yaml` after U1.1 completes)

- [ ] **Step 1:** Update `pyproject.toml`: remove `pytest-cov>=4.1`, add explicit `cryptography>=42.0` to `dev` (or keep runtime `pyjwt[crypto]`), add minimum security bounds (`certifi>=2026.10.18` and any needed bounds identified in Phase B Red audit).
- [ ] **Step 2:** Compile `requirements.lock` and `requirements-dev.lock` using `uv pip compile --universal` with `--custom-compile-command` header pointing to `pyproject.toml`. Remove `requirements.txt` and `requirements-dev.txt`.
- [ ] **Step 3:** Update `run.bat` (`pip install -r requirements.lock`) and `render.yaml` (`buildCommand: "pip install -r requirements.lock && pip install --no-deps ."`).
- [ ] **Step 4:** Sync `.\venv` (`uv pip sync requirements-dev.lock` or `.\venv\Scripts\pip.exe install -r requirements-dev.lock --upgrade` + `pip install --no-deps -e .`) and verify `uvx pip-audit -r requirements.lock`, `uvx pip-audit` in `venv`, and `.\venv\Scripts\pytest.exe`.

---

### Task 2 (U1.2): Frontend Next.js Security Upgrade (`@u1-frontend-next-sec`)

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1:** Inspect available patched `next@16.x` versions via `npm view next versions` and advisory details from Phase B Red `npm audit`.
- [ ] **Step 2:** Upgrade `next` and `eslint-config-next` in `frontend/package.json` to the identical patched release and regenerate `frontend/package-lock.json` cleanly via `npm install`.
- [ ] **Step 3:** Verify `npm audit`, `npm run lint`, `npx tsc --noEmit --incremental false`, `npm test`, and `npm run build` in `frontend/`.
- [ ] **Step 4:** Run controlled `next dev` smoke test: start `npm run dev`, wait for port 3000 HTTP 200 on `/`, verify no security-abort message, and terminate the entire process tree cleanly confirming port 3000 is closed.

---

### Task 3 (U1.3): Repository Hygiene, Config Cleanup & `AGENTS.md` (Coordinator)

**Files:**
- Modify: `.gitignore`
- Modify: `render.yaml` (remove redundant `BATCH_SIZE` entry while preserving `REFRESH_BATCH_SIZE: "50"`)
- Modify: `AGENTS.md` (add concise Python install/lockfile commands section under 60 lines delta, keeping total concise)
- Delete ephemeral folder: `.playwright-cli/`

- [ ] **Step 1:** Harden `.gitignore` with `*.db-wal`, `*.db-shm`, `*.sqlite*`, `.env.*`, `!.env.example`, `.playwright-cli/` (preserving existing rules).
- [ ] **Step 2:** Remove redundant `BATCH_SIZE` entry from `render.yaml`.
- [ ] **Step 3:** Remove `.playwright-cli/` ephemeral cache directory; inventory `portfolio.db`, `CSV_example.csv`, `backups/`, `SQL_supabase.txt` without deleting them.
- [ ] **Step 4:** Update `AGENTS.md` minimally with the new `pyproject.toml` / `requirements.lock` / `requirements-dev.lock` workflow.

---

### Task 4 (Phase D): Integrated Verification, Review & Atomic Commits (Coordinator)

- [ ] **Step 1:** Run full `code-review` and `blast-radius` check across `git diff`.
- [ ] **Step 2:** Run full integrated verification suite (`pytest`, `pip-audit`, `npm audit`, `npm run lint`, `tsc`, `npm test`, `npm run build`, port check).
- [ ] **Step 3:** Create 4 atomic conventional commits on `chore/u1-supply-chain-hygiene` (no `git push`, no auto-merge unless instructed; report PR readiness / status clearly).
