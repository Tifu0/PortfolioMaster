# 📈 PortfolioMaster

Local web application for managing, tracking, and analyzing your investment Watchlist portfolio, designed to replace traditional spreadsheet workflows (Google Sheets / Excel) with a fast, private experience free of cloud dependencies.

## 🚀 Quick Start

### On Windows (Recommended)
Double-click or run from the terminal:
```cmd
run.bat
```
This script will:
1. Automatically create the virtual environment (`venv`) if it doesn't exist.
2. Install the required dependencies (`requirements.txt`).
3. Launch the web application using Streamlit.

### Manual Setup
```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the application
streamlit run app.py
```

---

## 🗺️ Project Structure

The codebase follows a modular layered architecture to ensure each component has a clear, single responsibility:

```text
PortfolioMaster/
├── app.py                      # Entry point for the Streamlit UI
├── run.bat                     # 1-click quick launch script for Windows
├── requirements.txt            # Project dependencies (Streamlit, Pandas, yfinance, etc.)
├── pyproject.toml              # Python package metadata and standard installation config
├── pytest.ini                  # Test runner configuration (pytest)
├── .env.example                # Template for optional environment variables
├── .gitignore                  # Git exclusion rules (ignores venv, db, pycache)
│
├── src/portfoliomaster/        # Core application source code
│   ├── core/                   # Pure business logic and data models
│   │   ├── calculations.py     # Financial calculations (daily change, return, etc.)
│   │   ├── config.py           # Market mapping, Yahoo suffixes, and settings
│   │   └── models.py           # Dataclasses (Instrument, Quote, QuoteStatus, etc.)
│   │
│   ├── db/                     # Persistence layer (SQLite)
│   │   ├── connection.py       # Table initialization and connection management
│   │   └── repository.py       # Database operations (CRUD, queries)
│   │
│   ├── ingest/                 # Spreadsheet import and processing
│   │   ├── columns.py          # Column name detection and mapping
│   │   ├── parser.py           # CSV / Excel file parsing
│   │   ├── validator.py        # Validation and inconsistency detection
│   │   ├── normalizer.py       # Ticker normalization and data typing
│   │   └── import_session.py   # Import process orchestrator
│   │
│   ├── providers/              # Market data sources
│   │   ├── base.py             # Abstract base interface (MarketDataProvider)
│   │   ├── mock_provider.py    # Mock provider for offline local testing
│   │   └── yahoo_adapter.py    # Live Yahoo Finance adapter (via yfinance)
│   │
│   ├── refresh/                # Quote refresh engine
│   │   └── batch_runner.py     # Batch execution with retries and fault tolerance
│   │
│   └── ui/                     # Streamlit visual components
│       ├── components.py       # Interactive tables, filters, and controls
│       └── style.py            # Conditional formatting and status badges
│
└── tests/                      # Automated test suite
    ├── conftest.py             # Shared pytest fixtures
    ├── test_batch_runner.py    # Batch runner tests
    ├── test_calculations.py    # Math formula and calculation tests
    ├── test_db.py              # Database operation tests
    ├── test_ingest.py          # Import and normalization tests
    ├── test_providers.py       # Data provider tests
    └── test_refresh_functionality.py # Refresh integration and adapter tests
```

---

## 🧪 Running Tests

To verify that calculation logic, database persistence, and file imports are working properly:

```bash
# Activate the virtual environment if it isn't active:
venv\Scripts\activate

# Run tests:
pytest
```

---

## ⚙️ Optional Configuration

If you want to customize application behavior:
1. Copy the `.env.example` file and rename it to `.env`.
2. Edit the variables to your preference (e.g., custom database file path or refresh interval).

---

## 🔒 Privacy Disclaimer

- **Local-First:** All your portfolio data and quotes are stored locally on your machine (`portfolio.db`). No financial information is transmitted to external servers.
- **Market Data:** Price quotes are retrieved using the `yfinance` library from Yahoo Finance. This tool is intended solely for personal tracking and research. It does not execute trades nor does it constitute financial advice.

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. 

See the [LICENSE](LICENSE) file for full details. GPL-3.0 guarantees that PortfolioMaster remains free and open-source, provides explicit patent protection, and prohibits non-free closed-source redistribution.