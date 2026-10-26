# 📈 PortfolioMaster

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-emerald?style=for-the-badge&logo=vercel)](https://portfolio-master-sigma-peach.vercel.app/)
[![API Status](https://img.shields.io/badge/Backend%20API-Render-blue?style=for-the-badge&logo=render)](https://portfoliomaster-backend.onrender.com/health)
[![Interactive Docs](https://img.shields.io/badge/Swagger%20UI-Docs-purple?style=for-the-badge&logo=fastapi)](https://portfoliomaster-backend.onrender.com/docs)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/gpl-3.0)

**PortfolioMaster** is a high-performance investment Watchlist tracking and analytics platform. Supporting both **cloud multi-tenant production** (Next.js on Vercel + FastAPI on Render + Supabase PostgreSQL) and **local-first privacy** (Next.js + SQLite), it replaces traditional spreadsheet workflows (Google Sheets / Excel) with a modern, real-time, ultra-responsive dashboard.

- 🌐 **Live Web Application**: [https://portfolio-master-sigma-peach.vercel.app/](https://portfolio-master-sigma-peach.vercel.app/)
- ⚡ **Production Backend API**: [https://portfoliomaster-backend.onrender.com/](https://portfoliomaster-backend.onrender.com/)
- 📖 **Interactive API Documentation (Swagger)**: [https://portfoliomaster-backend.onrender.com/docs](https://portfoliomaster-backend.onrender.com/docs)

Built on a decoupled modern architecture:
- **Frontend**: **Next.js 16 (React 19)**, **TypeScript**, **Tailwind CSS v4**, and **@tanstack/react-table**.
- **Backend**: **FastAPI** REST API with **Uvicorn**, powered by **Python** core calculations, PostgreSQL (Supabase) / SQLite persistence, and live market quotes via **Yahoo Finance** (`yfinance`).


---

<img width="1919" height="1079" alt="Captura de pantalla 2026-10-17 175413" src="https://github.com/user-attachments/assets/47c9fa94-b971-41c8-987b-17a0a23aa751" />

---

## ✨ Features

- **📊 Interactive Watchlist Table**:
  - **📅 Inline Analysis Date Column**: Dedicated column for displaying the analysis date with single-click inline editing, keyboard shortcuts (`Enter` to save, `Escape` to cancel, blur to commit), and automatic price recalculation via Yahoo Finance.
  - **📝 Inline Research Notes & Descriptions**: Clickable document icon (`FileText`) on each ticker to view and edit company analysis notes, investment thesis, and comments directly inline with SQLite persistence.
  - **↔️ Interactive Column Resizing**: Google Sheets-style column width adjustment with drag handles, double-click to auto-reset individual columns, automatic `localStorage` persistence, and a **`Restore Columns`** button in the toolbar.
  - Multi-column sorting powered by TanStack Table, retaining column sort choices (e.g. Daily Change ascending) across page reloads.
  - Real-time instant search by ticker or company name.
  - Dynamic filters by market exchange and currency with single-row responsive layout.

- **📈 Portfolio Metric Cards & Header Status**:
  - Live summary statistics displayed at the top: Total active positions, Top gainer, Top loser, and Average daily change.
  - Modern runtime badge positioned in the top-right header displaying active auto-refresh interval and Yahoo Finance batch size (e.g. `Auto 60s · Batch 25`); during an active refresh, it switches to live batch progress (e.g. `Iniciando actualización...` then `Actualizando lote... · 6/11 (150/275)`).

- **🔄 Unified Market Data & Analysis Refresh Engine**:
  - One-click **`Update Quotes`** button that refreshes all live quotes via Yahoo Finance AND automatically resolves missing historical analysis prices and start-of-year (YTD) reference prices in one unified operation.
  - **High-Speed Concurrent Quote Engine**: Hybrid vectorization (`yf.download`) coupled with parallel `ThreadPoolExecutor` workers using lightweight Yahoo `fast_info` + resilient browser session headers, bypassing heavy OHLCV candle downloads and crumb rate limits. 30 symbols refresh in **1.2s - 1.5s**.
  - **Bulk Database Upsert (`upsert_market_quotes_batch`)**: Resolves existing quotes in a single SQL query (`WHERE provider_symbol IN (...)`) and flushes once, reducing remote PostgreSQL network round-trips from 60 down to 2 per batch (**95% latency reduction**).
  - **Request-Storm Prevention & Realtime Coalescing**: Frontend in-flight concurrency guards consolidate parallel fetch triggers; Supabase Realtime row updates are debounced and suppressed during active batch refreshes to eliminate CPU starvation on cloud web services (Render).
  - **Progressive Real-Time Streaming via Server-Sent Events (SSE)** (`GET /api/refresh/stream`): A centralized pub/sub broadcaster streams batch events (`start`, `batch`, `complete`) to the client for **both manual refreshes and scheduled background loops**.
  - **Incremental Per-Batch Persistence & Live Table Updates**: Quotes are committed to PostgreSQL / SQLite after each batch and immediately rendered in the UI table in real time, rather than blocking until all batches finish.
  - **Zero-Flicker State Preservation**: Incremental updates in `PortfolioProvider` and `WatchlistTable` strictly preserve table state — scroll position, active search filters, column sorting, column widths, and open inline editing (`Analysis Date` or `Research Notes`) are never interrupted or reset.
  - **Zero CORS Preflight Overhead**: Optimized simple HTTP requests, Next.js proxy rewrites (`/api/:path*`), and FastAPI `CORSMiddleware` with 24-hour preflight caching (`max_age=86400`) eliminate redundant `OPTIONS` round-trips.
  - **Adaptive Sync Heartbeat**: Adaptive background sync with intelligent log filtering to keep development consoles clean and signal-focused.
  
- **📥 CSV & Excel Spreadsheet Import**:
  - Drag-and-drop file upload supporting `.csv` and `.xlsx` files.
  - Two-step import workflow: dry-run validation with preview table, anomaly detection, and explicit database commit.
  - Automatic column mapping and ticker normalization (e.g. `BME:MAP`, `EPA:MC`, `US` prefixes).

- **💾 Backup, Export & Safe Restoration System**:
  - **Dedicated "Backup & Export" View & Tab**: Accessible directly from the main navigation bar (`/backup`), offering full-page access to watchlist exports (`.xlsx`, `.csv`, `.json`), SQLite snapshots (`.db`), and backup restorations without relying solely on modals.
  - **Multi-Format Watchlist Export**: Quick download of the complete watchlist into **Excel (`.xlsx`)**, **CSV (`.csv`)**, or structured **JSON (`.json`)** with live quotes, calculated returns, and research notes.
  - **100% Round-Trip Ingest Compatibility**: Column headers and numeric formats in exported `.xlsx` and `.csv` files are 100% compatible with the import pipeline—enabling seamless re-import without data loss (preserving target prices, analysis benchmarks, start-of-year YTD prices, and notes).
  - **Atomic SQLite Snapshots (`.db`)**: Safe snapshot creation using Python's native `sqlite3.Connection.backup()` API, avoiding file locks and corruption during concurrent quote refreshes.
  - **Automatic Local Safety Backups**: Automated snapshots saved to `backups/` prior to any destructive operation (`DELETE /api/database`, `POST /api/import/confirm`, or database restorations), with automatic rotation maintaining the 10 most recent snapshots.
  - **SQLite & JSON Restore Validator**: Upload or drag-and-drop restore with `PRAGMA integrity_check` verification, schema validation, and 1-click restore from local automatic snapshots with confirmation guards.


- **⚙️ Customizable Action Toolbar with Persistence & Row Height Controller**:
  - **Toolbar Customization Popover**: Positioned at the far right of the action toolbar, allowing users to toggle the visibility of individual action buttons (Update Quotes, Add Instrument, Restore Columns, Row Height, Export / Copy, Import Values, and Clear DB).
  - **Safe Database Reset Protection**: The destructive `Clear DB` button is hidden by default and protected by both toolbar visibility toggle and confirmation modal guard.
  - **Client-Side Persistence & Hydration Safety**: Button visibility and density preferences are remembered across page reloads via `localStorage` (`portfoliomaster_toolbar_config` and `portfoliomaster_row_height`) with hydration mismatch protection in Next.js 16.
  - **Reset to Defaults**: 1-click restore to recommended default toolbar layout and standard row height.

---

## 🚀 Quick Start

### Windows (1-Step Launch)
Run the automated script from the root directory or double-click it:
```cmd
run.bat
```
This script automatically:
1. Sets up the Python virtual environment (`venv`) and installs backend requirements (`requirements.txt`).
2. Installs Node.js dependencies in `frontend/` (`npm install`) if not present.
3. Launches the **FastAPI backend** on `http://localhost:8000`.
4. Launches the **Next.js frontend** on `http://localhost:3000`.

---

### Manual Setup

#### 1. Start the Backend (FastAPI)
```bash
# Create and activate Python virtual environment
python -m venv venv
venv\Scripts\activate    # On Windows (or 'source venv/bin/activate' on Linux/macOS)

# Install dependencies
pip install -r requirements.txt

# Start FastAPI server
uvicorn backend.api.main:app --reload --port 8000
```
- **API Server**: [http://localhost:8000](http://localhost:8000)
- **Interactive API Documentation (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative Documentation (ReDoc)**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### 2. Start the Frontend (Next.js)
In a separate terminal window:
```bash
cd frontend

# Install dependencies
npm install

# Start Next.js development server
npm run dev
```
- **Web Application**: [http://localhost:3000](http://localhost:3000)

---

### ⚙️ Environment Configuration (`.env`)

> [!NOTE]
> Having a `.env` file is **completely optional**. PortfolioMaster works out-of-the-box without `.env` using robust built-in defaults (`PORTFOLIOMASTER_DB_PATH="portfolio.db"`, `REFRESH_INTERVAL_SECONDS=300`, `REFRESH_BATCH_SIZE=10`, and frontend `API_BASE_URL="http://localhost:8000"`).

You can customize the application behavior by creating or editing `.env` in the project root (see [.env.example](.env.example))

Refresh interval and batch size are dynamically exposed to the frontend via `/api/config` and displayed in the real-time status badge at the top-right of the dashboard.

---

## 🗺️ Project Structure

```text
PortfolioMaster/
├── backend/
│   ├── api/
│   │   └── main.py             # FastAPI application and REST endpoints
│   └── tests/
│       ├── test_api.py         # Backend API integration tests
│       └── test_backup_api.py  # Backup & Export API integration tests
│
├── frontend/                   # Next.js web application (App Router)
│   ├── app/                    # Routes, layouts, loading skeletons, and error handling
│   ├── components/             # React components (WatchlistTable, BackupExportView, BackupExportModal, MetricCards, ImportView, ManualEntryModal)
│   ├── context/                # React 19 PortfolioProvider and reactive hooks (usePortfolio)
│   ├── lib/                    # Typed API client (api.ts) and TypeScript models (types.ts)
│   ├── public/                 # Static assets, llms.txt, robots.txt
│   ├── scripts/                # Automated verification and test scripts
│   └── next.config.ts          # Next.js config with same-origin/api rewrites to the FastAPI backend
│
├── src/portfoliomaster/        # Core business logic and persistence (Pure Python)
│   ├── backup/                 # SQLite atomic snapshots, auto-safety backups, and multi-format exporters (CSV/Excel/JSON)
│   ├── core/                   # Financial formulas, calculations, models, and configuration
│   ├── db/                     # SQLite persistence layer (connection and repository CRUD)
│   ├── ingest/                 # Spreadsheet parser, normalizer, and validator
│   ├── providers/              # Market data providers (Yahoo Finance adapter & mock)
│   └── refresh/                # Batch quote runner with fault tolerance
│
├── backups/                    # Local automatic safety snapshots (rotated, git-ignored)
├── tests/                      # Core test suite (calculations, database, ingest, providers, backup/export, batch_runner)
├── portfolio.db                # Local SQLite database file
├── requirements.txt            # Python dependencies (FastAPI, Pandas, openpyxl, yfinance, etc.)
├── pyproject.toml              # Python package metadata
├── pytest.ini                  # Pytest configuration
└── run.bat                     # Windows 1-step launch script
```

---

## 🔌 API Reference

The backend exposes clean JSON REST endpoints consumed by the Next.js frontend:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/positions` | List active instruments with quotes and calculated financial returns (Daily, YTD, vs. Analysis, Decline to Target) |
| `GET` | `/api/metrics` | Portfolio summary metrics (total count, top gainer, top loser, average variation) |
| `GET` | `/api/instruments` | Raw list of all registered instruments |
| `GET` | `/api/instruments/{ticker}` | Retrieve details for a specific instrument |
| `POST` | `/api/instruments` | Create a new instrument with automatic resolution of live quotes, historical analysis price, and YTD price |
| `PUT` | `/api/instruments/{ticker}` | Update fields of an existing instrument (supports ticker renaming, currency, exchange, targets, analysis price/date, YTD price/date, notes) |
| `DELETE` | `/api/instruments/{ticker}` | Delete an instrument from the watchlist |
| `POST` | `/api/instruments/{ticker}/refresh` | Refresh market quote and auto-resolve missing analysis and YTD prices for a single instrument |
| `POST` | `/api/refresh` | Batch-refresh quotes from Yahoo Finance using vectorized multi-threaded downloads with per-batch SQLite persistence. |
| `GET` | `/api/refresh/stream` | Server-Sent Events (SSE) stream emitting real-time batch progress (`mode=listen` for continuous pub/sub listener or `?trigger=1` to initiate) |
| `POST` | `/api/instruments/{ticker}/fetch-analysis-price` | Fetch historical quote from Yahoo Finance for instrument's analysis date (with resilient lookback and same-day fallback) |
| `POST` | `/api/instruments/{ticker}/fetch-ytd-price` | Fetch start-of-year quote from Yahoo Finance for instrument for current year |
| `POST` | `/api/instruments/resolve-missing-analysis-prices` | Auto-resolve historical analysis reference prices from Yahoo Finance |
| `POST` | `/api/instruments/resolve-missing-ytd-prices` | Auto-resolve start-of-year (YTD) reference prices from Yahoo Finance |
| `GET` | `/api/config` | Retrieve runtime configuration (refresh interval, batch size, last refresh status), and live batch progress |
| `POST` | `/api/import/preview` | Dry-run validation of an uploaded CSV/Excel spreadsheet |
| `POST` | `/api/import/confirm` | Commit validated spreadsheet instruments into the database (creates safety backup) |
| `DELETE` | `/api/database` | Reset the SQLite database completely (creates safety backup) |
| `GET` | `/api/export/csv` | Download active watchlist as an ingest-compatible `.csv` file |
| `GET` | `/api/export/excel` | Download active watchlist as a styled, ingest-compatible `.xlsx` spreadsheet |
| `GET` | `/api/export/json` | Download active watchlist as a structured, versioned `.json` dump |
| `GET` | `/api/backup/download` | Download an atomic, thread-safe raw SQLite snapshot (`.db`) |
| `POST` | `/api/backup/restore` | Restore database from an uploaded `.db` or `.json` file with pre-restore safety snapshot |
| `GET` | `/api/backup/list` | List available automatic local snapshots in `backups/` |
| `POST` | `/api/backup/restore/{filename}` | 1-click restore from a local snapshot file |

---

## 🧪 Testing

Both backend and frontend contain automated test suites.

### Backend & Core Tests (Python)

Pytest is configured in [`pytest.ini`](pytest.ini) with strict timeouts (`--timeout=10`), unbuffered real-time stdout (`-s`, `-u`), and automatically excludes live network tests by default (`-m "not network"`) to guarantee fast, deterministic runs without hanging on rate limits.

1. **Standard Execution (Offline / Fast - Default):**
   Runs all unit and integration tests using mocks (80 tests):
   ```bash
   venv\Scripts\python -u -m pytest
   ```

2. **Network Integration Tests (Live Yahoo Finance):**
   Runs only the tests that connect to external APIs (Yahoo Finance):
   ```bash
   venv\Scripts\python -u -m pytest -m network
   ```

3. **Complete Suite (All Tests):**
   Runs both offline and live network tests:
   ```bash
   venv\Scripts\python -u -m pytest -m ""
   ```

### Frontend Tests (TypeScript)
Run contract verification and component tests:
```bash
cd frontend
npm test
```

---

## ☁️ Production Deployment Architecture

PortfolioMaster supports high-availability, multi-tenant cloud deployment:

- **Frontend**: **Next.js 16 (App Router)** deployed to **Vercel** (`frontend` as root directory)  
  👉 **Live App**: [https://portfolio-master-sigma-peach.vercel.app/](https://portfolio-master-sigma-peach.vercel.app/)
- **Backend API**: **FastAPI** ASGI web service deployed to **Render** with Uvicorn  
  👉 **API Base**: [https://portfoliomaster-backend.onrender.com/](https://portfoliomaster-backend.onrender.com/)  
  👉 **Swagger Docs**: [https://portfoliomaster-backend.onrender.com/docs](https://portfoliomaster-backend.onrender.com/docs)
- **Database**: **Supabase PostgreSQL** with Row-Level Security (RLS) policies and shared `market_quotes` decoupling.
- **Authentication**: **Supabase Auth** with cryptographic JWT verification (`HS256`, audience `authenticated`).
- **Local Development**: Isolated SQLite backend (`portfolio.db`) with automatic fallback when `DATABASE_URL` is unset.

### 1. Render Deployment (FastAPI Web Service)
1. Link repository to Render and create a **Web Service** using `render.yaml`.
2. Configure settings:
   - **Environment**: Python 3.12.6
   - **Build Command**: `pip install -r requirements.txt && pip install .`
   - **Pre-Deploy Command**: `alembic upgrade head`
   - **Start Command**: `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`
3. Set Environment Variables:
   - `DATABASE_URL`: `postgresql+psycopg://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres`
   - `SUPABASE_JWT_SECRET`: From Supabase Dashboard -> Project Settings -> API -> JWT Secret
   - `SUPABASE_URL`: `https://[REF].supabase.co`
   - `CORS_ORIGINS`: `https://portfolio-master-sigma-peach.vercel.app`
   - `ENVIRONMENT`: `production`

### 2. Vercel Deployment (Next.js App Router)
1. Import repository on Vercel.
2. Configure settings:
   - **Root Directory**: `frontend`
   - **Framework Preset**: `Next.js`
3. Set Environment Variables:
   - `NEXT_PUBLIC_API_URL`: `https://portfoliomaster-backend.onrender.com`
   - `NEXT_PUBLIC_SUPABASE_URL`: `https://[REF].supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`: Your Supabase anon public key

---

## 🚚 Migrating Legacy SQLite Data to Supabase PostgreSQL

To migrate an existing SQLite database (`portfolio.db`) or JSON v1.0 backup into your multi-tenant Supabase PostgreSQL database:

```bash
# 1. Dry run (validation, duplicate detection, orphan check, checksum reconciliation - 0 DB writes)
python scripts/migrate_sqlite_to_web.py --sqlite portfolio.db --user-id <TARGET-USER-UUID> --db-url "postgresql+psycopg://..." --dry-run

# 2. Live migration (atomic commit with rollback safety)
python scripts/migrate_sqlite_to_web.py --sqlite portfolio.db --user-id <TARGET-USER-UUID> --db-url "postgresql+psycopg://..."

# 3. Rollback (if ever needed to cleanly purge migrated user records)
python scripts/migrate_sqlite_to_web.py --rollback --user-id <TARGET-USER-UUID> --db-url "postgresql+psycopg://..."
```

---

## 🔒 Privacy & Architecture Modes

- **Multi-Tenant Cloud Mode:** When `DATABASE_URL` is set to Supabase PostgreSQL, all user data is partitioned by `user_id` authenticated via Supabase JWT with Row Level Security.
- **Local-First Mode:** When `DATABASE_URL` is unset in development, data is stored locally in SQLite (`portfolio.db`).

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. See the [LICENSE](LICENSE) file for complete details.
