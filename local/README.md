# Local Development & Data Workspace (`local/`)

This directory holds untracked, git-ignored local data files and step-by-step instructions for running **PortfolioMaster** locally.

## Files in This Folder (Git-Ignored)

| File | Purpose |
|---|---|
| `local/portfolio.db` | Local SQLite database used when running without Supabase PostgreSQL. |
| `local/CSV_example.csv` | Sample watchlist CSV file compatible with the `/import` dry-run and confirm pipeline. |
| `local/SQL_supabase.txt` | Complete PostgreSQL DDL script (tables, indexes, triggers, and RLS policies) for bootstrapping a Supabase project via the SQL Editor. |

> [!NOTE]
> Only `local/README.md` is tracked in Git. Database, CSV, and SQL files inside `local/` are ignored via `.gitignore`.

---

## Running PortfolioMaster Locally

### Option A: Windows 1-Step Launch
From the repository root:
```cmd
run.bat
```
This creates `venv` (if missing), installs Python runtime dependencies from `requirements.lock`, installs `frontend/node_modules` (if missing), and starts both services:
- **Frontend:** `http://localhost:3000`
- **Backend API:** `http://localhost:8000`
- **Swagger UI:** `http://localhost:8000/docs`

### Option B: Manual Setup

#### 1. Backend (FastAPI)
From the repository root:
```bash
python -m venv venv
venv\Scripts\activate          # Windows (or: source venv/bin/activate on Linux/macOS)

# Runtime dependencies (or use requirements-dev.lock && pip install --no-deps -e . for tests)
pip install -r requirements.lock

# Start API server (reads .env when present)
uvicorn backend.api.main:app --reload --port 8000 --env-file .env
```

- **Using `local/portfolio.db` directly:** Set `DATABASE_URL=sqlite:///local/portfolio.db` in `.env` (otherwise, when `DATABASE_URL` is unset in non-production mode, the backend defaults to `portfolio.db` in the repository root).
- **Environment template:** Copy `.env.example` to `.env` and configure `SUPABASE_URL` or `SUPABASE_JWT_SECRET` (at least 32 bytes for HS256).

#### 2. Frontend (Next.js)
In a separate terminal from `frontend/`:
```bash
cd frontend
npm install
npm run dev
```
Copy `frontend/.env.example` to `frontend/.env.local` and configure `API_BASE_URL` (defaults to `http://localhost:8000` in development), `NEXT_PUBLIC_SUPABASE_URL`, and `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

---

## Importing Sample Data & Supabase Migration

1. **Sample CSV import:** Open `http://localhost:3000/import` and upload `local/CSV_example.csv` to preview and import sample instruments.
2. **Supabase schema setup:** Copy the contents of `local/SQL_supabase.txt` into the Supabase SQL Editor and run it (see [`docs/deployment.md`](../docs/deployment.md)).
3. **Migrate local SQLite data to Supabase PostgreSQL:**
   ```bash
   # Dry run (0 DB writes)
   python scripts/migrate_sqlite_to_web.py --sqlite local/portfolio.db --user-id <TARGET-USER-UUID> --db-url "postgresql+psycopg://..." --dry-run

   # Live migration
   python scripts/migrate_sqlite_to_web.py --sqlite local/portfolio.db --user-id <TARGET-USER-UUID> --db-url "postgresql+psycopg://..."

   # Rollback migrated records if needed
   python scripts/migrate_sqlite_to_web.py --rollback --user-id <TARGET-USER-UUID> --db-url "postgresql+psycopg://..."
   ```
