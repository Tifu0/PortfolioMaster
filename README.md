# 📈 PortfolioMaster

**PortfolioMaster** is a high-performance, local-first web application designed for tracking, managing, and analyzing your investment Watchlist. It replaces traditional spreadsheet workflows (Google Sheets / Excel) with a modern, ultra-responsive, and 100% private user experience without any cloud dependencies.

Built on a decoupled modern architecture:
- **Frontend**: **Next.js 16 (React 19)**, **TypeScript**, **Tailwind CSS v4**, and **@tanstack/react-table**.
- **Backend**: **FastAPI** REST API with **Uvicorn**, powered by **Python** core calculations, SQLite persistence, and live market quotes via **Yahoo Finance** (`yfinance`).

---

<img width="1919" height="1079" alt="Captura de pantalla 2026-10-17 175413" src="https://github.com/user-attachments/assets/47c9fa94-b971-41c8-987b-17a0a23aa751" />

---

## ✨ Features

- **📊 Interactive Watchlist Table**:
  - Pre-computed financial metrics: Daily Variation (`±%`), **Year-To-Date (YTD) Variation (`±%`)** relative to start-of-year price, Return vs. Analysis Price (`±%`), and Required Decline to Target Price (`±%`).
  - **📅 Start-of-Year (YTD) & Analysis Benchmarks**: Contextual sub-labels showing the exact reference price and date beneath percentage variations (e.g., `5,50 € (2026-01-02)`).
  - **📝 Inline Research Notes & Descriptions**: Clickable document icon (`FileText`) on each ticker to view and edit company analysis notes, investment thesis, and comments directly inline with SQLite persistence.
  - **↔️ Interactive Column Resizing**: Google Sheets-style column width adjustment with drag handles, double-click to auto-reset individual columns, automatic `localStorage` persistence, and a **`Restore Columns`** button in the toolbar.
  - Multi-column sorting powered by TanStack Table.
  - Real-time instant search by ticker or company name.
  - Dynamic filters by market exchange and currency with single-row responsive layout.

- **📈 Portfolio Metric Cards & Header Status**:
  - Live summary statistics displayed at the top: Total active positions, Top gainer, Top loser, and Average daily change.
  - Modern runtime badge positioned in the top-right header displaying active auto-refresh interval and Yahoo Finance batch size (e.g. `Auto 60s · Batch 25`).

- **🔄 Unified Market Data & Analysis Refresh Engine**:
  - One-click **`Update Quotes`** button that refreshes all live quotes via Yahoo Finance AND automatically resolves missing historical analysis prices and start-of-year (YTD) reference prices in one unified operation.
  - Configurable background auto-refresh loop and batch processing with timeout protection and retry strategies.

- **📥 CSV & Excel Spreadsheet Import**:
  - Drag-and-drop file upload supporting `.csv` and `.xlsx` files.
  - Two-step import workflow: dry-run validation with preview table, anomaly detection, and explicit database commit.
  - Automatic column mapping and ticker normalization (e.g. `BME:MAP`, `EPA:MC`, `US` prefixes).

- **➕ Manual Position Management**:
  - Modal form to quickly register new instruments or edit existing targets, analysis prices, start-of-year YTD prices, and custom research notes, with instant Yahoo Finance lookups.
  - Safe instrument deletion and one-click database reset with confirmation guards.

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

You can customize the application behavior by creating or editing `.env` in the project root (see [.env.example](.env.example)):

```ini
# Path to SQLite database file (default: portfolio.db)
PORTFOLIOMASTER_DB_PATH=portfolio.db

# Auto-refresh interval in seconds (default: 300, set to 0 to disable background auto-refresh)
REFRESH_INTERVAL_SECONDS=60

# Number of ticker symbols sent per batch to Yahoo Finance (default: 10)
REFRESH_BATCH_SIZE=25
```

These variables are dynamically exposed to the frontend via `/api/config` and displayed in the real-time status badge at the top-right of the dashboard.

---

## 🗺️ Project Structure

```text
PortfolioMaster/
├── backend/
│   ├── api/
│   │   └── main.py             # FastAPI application and REST endpoints
│   └── tests/
│       └── test_api.py         # Backend API integration tests (28 tests)
│
├── frontend/                   # Next.js web application (App Router)
│   ├── app/                    # Routes, layouts, loading skeletons, and error handling
│   ├── components/             # React components (WatchlistTable, MetricCards, ImportView, ManualEntryModal)
│   ├── lib/                    # Typed API client (api.ts) and TypeScript models (types.ts)
│   ├── public/                 # Static assets, llms.txt, robots.txt
│   └── scripts/                # Automated verification and test scripts
│
├── src/portfoliomaster/        # Core business logic and persistence (Pure Python)
│   ├── core/                   # Financial formulas, calculations, models, and configuration
│   ├── db/                     # SQLite persistence layer (connection and repository CRUD)
│   ├── ingest/                 # Spreadsheet parser, normalizer, and validator
│   ├── providers/              # Market data providers (Yahoo Finance adapter & mock)
│   └── refresh/                # Batch quote runner with fault tolerance
│
├── tests/                      # Core test suite (calculations, database, ingest, providers)
├── portfolio.db                # Local SQLite database file
├── requirements.txt            # Python dependencies (FastAPI, Pandas, yfinance, etc.)
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
| `POST` | `/api/instruments` | Create or update an instrument manually |
| `PUT` | `/api/instruments/{ticker}` | Update fields of an existing instrument (targets, analysis price/date, YTD price/date, notes) |
| `DELETE` | `/api/instruments/{ticker}` | Delete an instrument from the watchlist |
| `POST` | `/api/instruments/{ticker}/refresh` | Refresh market quote and auto-resolve analysis and YTD prices for a single instrument |
| `POST` | `/api/refresh` | Batch-refresh quotes from Yahoo Finance and resolve missing analysis and YTD prices |
| `POST` | `/api/instruments/{ticker}/fetch-analysis-price` | Fetch historical quote from Yahoo Finance for instrument's analysis date |
| `POST` | `/api/instruments/{ticker}/fetch-ytd-price` | Fetch start-of-year quote from Yahoo Finance for instrument for current year |
| `POST` | `/api/instruments/resolve-missing-analysis-prices` | Auto-resolve historical analysis reference prices from Yahoo Finance |
| `POST` | `/api/instruments/resolve-missing-ytd-prices` | Auto-resolve start-of-year (YTD) reference prices from Yahoo Finance |
| `GET` | `/api/config` | Retrieve runtime configuration (refresh interval, batch size, last refresh status) |
| `POST` | `/api/import/preview` | Dry-run validation of an uploaded CSV/Excel spreadsheet |
| `POST` | `/api/import/confirm` | Commit validated spreadsheet instruments into the database |
| `DELETE` | `/api/database` | Reset the SQLite database completely |

---

## 🧪 Testing

Both backend and frontend contain automated test suites.

### Backend & Core Tests (Python)
Run all 54 unit and integration tests with `pytest`:
```bash
venv\Scripts\activate
pytest
```

### Frontend Tests (TypeScript)
Run contract verification and component tests:
```bash
cd frontend
npm test
```

---

## 🔒 Privacy & Local-First Disclaimer

- **100% Local-First:** All portfolio data, analysis notes, and quotes are stored locally in your SQLite database (`portfolio.db`). No financial information or user data is ever sent to third-party cloud servers.
- **Market Data:** Price quotes are retrieved directly from Yahoo Finance via `yfinance`.
- **Personal Use:** This application is intended solely for personal tracking and research. It does not execute live financial transactions or provide investment advice.

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. See the [LICENSE](LICENSE) file for complete details.
