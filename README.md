# 📈 PortfolioMaster

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-emerald?style=for-the-badge&logo=vercel)](https://portfolio-master-sigma-peach.vercel.app/)
[![API Status](https://img.shields.io/badge/Backend%20API-Render-blue?style=for-the-badge&logo=render)](https://portfoliomaster-backend.onrender.com/health)
[![Interactive Docs](https://img.shields.io/badge/Swagger%20UI-Docs-purple?style=for-the-badge&logo=fastapi)](https://portfoliomaster-backend.onrender.com/docs)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/gpl-3.0)

**PortfolioMaster** is an investment watchlist tracking and price-target analytics platform. It supports **multi-tenant cloud production** (Next.js on Vercel + FastAPI on Render + Supabase PostgreSQL with RLS) as well as **local-first execution** (SQLite fallback when `DATABASE_URL` is unset).

- 🌐 **Live App**: [https://portfolio-master-sigma-peach.vercel.app/](https://portfolio-master-sigma-peach.vercel.app/)
- ⚡ **Backend API**: [https://portfoliomaster-backend.onrender.com/](https://portfoliomaster-backend.onrender.com/)
- 📖 **Swagger Docs**: [https://portfoliomaster-backend.onrender.com/docs](https://portfoliomaster-backend.onrender.com/docs)

---

<img width="1919" height="1079" alt="PortfolioMaster Watchlist Dashboard" src="https://github.com/user-attachments/assets/47c9fa94-b971-41c8-987b-17a0a23aa751" />

---

## ✨ Key Features

- **📊 Virtualized Interactive Watchlist (`WatchlistTable`)**:
  - Tracks live price, daily variation, YTD variation, return since your `analysis_date`, and **Decline to Target** with visual proximity alerts.
  - **Inline Analysis Date & Research Notes**: Edit analysis dates inline (`Enter`/`Blur` saves and resolves historical Yahoo quotes) and expand row-level thesis notes without rebuilding columns or re-rendering other rows.
  - **Responsive & Accessible UI**: Full EN/ES bilingual support (`translations.ts`), dark theme, mobile (`375px`) and desktop (`1280px`) layouts, customizable toolbar switches (`role="switch"`), row-height presets (`32–88px`), column sorting/sizing persisted via SSR-safe `localStorage`.

- **🔄 Real-Time Market Refresh & Multi-Tenant SSE**:
  - Hybrid batch quote engine (`yf.download` + `ThreadPoolExecutor` + Yahoo `fast_info`) with per-user refresh cooldown (`RefreshRun`) and decoupled global `market_quotes` storage.
  - Split refresh pipeline: `POST /api/refresh` triggers refreshes while `GET /api/refresh/stream` streams tenant-filtered progress events (`asyncio.Queue`) to merge deltas smoothly in the UI.
  - Thread-safe bounded read cache with SHA-256 `ETag` / `304 Not Modified` support and idle-aware background scheduling.

- **📥 Spreadsheet Import, Export & Backups**:
  - Two-step `.csv` / `.xlsx` import (`POST /api/import/preview` dry-run + `POST /api/import/confirm`) with formula-injection sanitization and row/size bounds.
  - Dedicated `/import` and `/backup` views supporting ingest-compatible exports (`.xlsx`, `.csv`, `.json`), JSON backups, and SQLite snapshots in local mode.

- **🔒 Security & Multi-Tenant Isolation**:
  - Browser traffic routes exclusively through Next.js same-origin `/api/[...path]` proxy using `HttpOnly` Supabase SSR session cookies (`API_BASE_URL` never exposed to the client).
  - Strict Supabase JWT verification (`HS256`/`RS256`/`ES256`, `role == "authenticated"`) and `user_id` tenant scoping across PostgreSQL queries and SSE streams.

---

## 🗺️ Project Structure

```text
PortfolioMaster/
├── backend/api/
│   ├── main.py                 # FastAPI entrypoint, lifespan, and background scheduler
│   ├── dependencies.py         # DI wiring (stores, refresh coordinator, auth guards)
│   ├── activity.py             # Client activity tracker for idle scheduler gating
│   ├── routers/                # Thin HTTP routers (config, positions, instruments, refresh, import_export, backup)
│   └── services/               # Domain services, SSE broker, and bounded read cache
├── src/portfoliomaster/
│   ├── core/                   # Financial models, calculations, config, canonical parsing.py
│   ├── db/                     # PortfolioStore port, SqliteWatchlistStore, PostgresWatchlistStore, schema.py
│   ├── providers/              # Thread-safe YahooAdapter and MockProvider
│   ├── ingest/                 # Spreadsheet parsing, normalization, and validation
│   ├── backup/                 # CSV/Excel/JSON exporters and SQLite backup helpers
│   └── refresh/                # Fault-tolerant batch runner
├── frontend/
│   ├── app/                    # Next.js 16 App Router pages (/, /import, /backup), auth & /api/[...path] proxy
│   ├── components/
│   │   ├── watchlist/          # WatchlistTable orchestrator + memoized InlineDateCell / InstrumentDescriptionPanel, toolbar, popovers
│   │   ├── instrument-modal/   # ManualEntryModal shell + AddInstrumentForm / EditInstrumentForm
│   │   └── backup/             # Dedicated backup/export/restore sections
│   ├── context/                # AuthContext, LanguageContext, PortfolioContext, PortfolioRefreshContext
│   ├── lib/                    # API client, SSR-safe storage.ts, watchlist-formatters.ts, instrument-constants.ts, translations.ts
│   └── scripts/                # Behavioral unit & SSR verification suites (npm test)
├── alembic/                    # Chained PostgreSQL/SQLite migrations
├── docs/specs/                 # Architecture & Spec-TDD specifications (01..07)
├── tests/                      # Consolidated Pytest suites (unit/, integration/, security/)
├── pyproject.toml              # Single source of truth for Python dependencies
└── requirements*.lock          # Deterministic runtime and dev lockfiles (uv)
```

For contributor conventions and Spec-TDD rules, see [`AGENTS.md`](AGENTS.md) and [`local/README.md`](local/README.md).

---

## 🔌 API Overview

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Readiness probe (`/healthcheck`, `/api/health`) |
| `GET` | `/api/config` | Runtime refresh settings and active run status |
| `GET` | `/api/positions`, `/api/metrics` | Watchlist rows with computed returns and portfolio summary metrics |
| `GET/POST/PUT/DELETE` | `/api/instruments`, `.../{ticker}` | Instrument CRUD, plus `GET /api/instruments/check-yahoo` |
| `POST` | `/api/instruments/{ticker}/fetch-analysis-price`, `.../fetch-ytd-price` | Historical analysis and start-of-year price resolution |
| `POST` | `/api/refresh`, `.../instruments/{ticker}/refresh` | Trigger batch or single-ticker quote refresh |
| `GET` | `/api/refresh/stream` | Tenant-isolated SSE progress stream |
| `POST` | `/api/import/preview`, `/api/import/confirm` | Dry-run preview and transactional spreadsheet import |
| `GET` | `/api/export/{csv,excel,json}` | Download watchlist in CSV, Excel, or JSON |
| `GET/POST/DELETE` | `/api/backup/*`, `/api/database` | Backup download/restore and database reset |

---

## 🧪 Testing

### Backend (`tests/`)
Install dev dependencies from lockfiles (never edit lockfiles by hand):
```bash
pip install -r requirements-dev.lock && pip install --no-deps -e .
```

Run tests (`pytest.ini` skips live network tests by default via `-m "not network"`):
```bash
pytest              # Offline unit/integration/security suite (129 tests)
pytest -m network   # Live Yahoo Finance network tests (1 test)
pytest -m ""        # Complete suite (130 tests)
```

### Frontend (`frontend/`)
```bash
cd frontend
npm run lint
npx tsc --noEmit --incremental false
npm test            # 7 behavioral & SSR test suites
npm run build
```

---

## ☁️ Deployment Architecture

- **Backend (Render via `render.yaml`)**: Python `3.12.6`, build `pip install -r requirements.lock && pip install --no-deps .`, pre-deploy `alembic upgrade head`, start `uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
  - Key env vars: `DATABASE_URL` (Supabase pooler), `SUPABASE_URL`, `SUPABASE_JWT_SECRET` (if `HS256`), `CORS_ORIGINS`, `ENVIRONMENT=production`, `REFRESH_INTERVAL_SECONDS=300`, `REFRESH_COOLDOWN_SECONDS=120`, `REFRESH_BATCH_SIZE=50`.
- **Frontend (Vercel, root `frontend/`)**: Next.js 16 + Tailwind CSS v4.
  - Key env vars: `API_BASE_URL` (server-side proxy target to Render), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- **Local Mode**: Leave `DATABASE_URL` unset for isolated SQLite persistence (`portfolio.db`); see [`local/README.md`](local/README.md).
