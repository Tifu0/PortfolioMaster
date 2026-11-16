# Watchlist Manual Entry, Ticker Update & Historical Price Resolution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve 4 core functional and UX issues in PortfolioMaster: hide analysis price in creation mode, provide single-row refresh auto-resolution for analysis metrics, add an explicit ticker change & sync button in edit mode, cleanly handle ticker renaming without stale metadata in SQLite/API, and implement a resilient Yahoo Finance historical quote fallback for same-day and closed markets.

**Architecture:**
- Backend: Enhance `_fetch_historical_quote_and_date` in `backend/api/main.py` and `YahooAdapter` with a 10-day lookback window plus same-day / closed market fallback (`fast_info` / `period="5d"`).
- Backend: Update `POST /api/instruments` and `POST /api/instruments/{ticker}/refresh` to resolve both `analysis_reference_price` and `start_of_year_price` automatically, populating `variation_since_analysis` in `/api/positions`.
- Backend: Enhance `PUT /api/instruments/{ticker}` and `InstrumentUpdate` model to accept `currency` and `exchange`, resolve new company name when changing ticker, and update the associated quote row cleanly.
- Frontend: In `ManualEntryModal.tsx`, remove `Precio Ref. Análisis` from creation mode while retaining it in edit mode. Add the "Confirmar cambio y actualizar datos" button next to the valid ticker banner to overwrite all metadata and reference prices with the new ticker's data.

**Tech Stack:** Next.js 16 / React 19 / TypeScript, FastAPI, Python 3.12, SQLite, `yfinance`, Tailwind CSS v4, `pytest`.

**Spec:** User prompt requirements covering Issues 1, 2, 3, and 4.

## Global Constraints
- Preserve zero-F5 reactive updates via `PortfolioContext.refreshPortfolioData`.
- Strict typing on API payloads and React components.
- Never crash on Yahoo Finance lookups for today's date, weekends, or closed market hours.
- Maintain full compatibility with existing unit tests in `pytest` and frontend verification scripts in `npm test`.

## Review Focus
1. Ticker rename must not leave orphaned quotes or overwrite wrong records in SQLite (`WHERE id = ?`).
2. When creating a company with analysis date = today, `analysis_reference_price` and `variation_since_analysis` must immediately appear in `GET /api/positions`.
3. Clicking single row refresh on an instrument missing `analysis_reference_price` must resolve it and calculate `Return vs. Analysis Price (%)`.
4. Editing a ticker in `ManualEntryModal` and clicking "Confirmar cambio y actualizar datos" must overwrite old company name, currency, exchange, live price, YTD price, and analysis price.
5. Yahoo Finance lookup on a weekend or closed market for today's date must gracefully return the latest available price instead of throwing a 404 error.

---

### Task 1: Resilient Historical Quote Fallback in Backend (Issue 4)

**Files:**
- Modify: `backend/api/main.py:828-875`
- Modify: `src/portfoliomaster/providers/yahoo_adapter.py:200-260`
- Test: `tests/test_providers.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `yf.Ticker`, `date`, `provider_symbol`.
- Produces: `_fetch_historical_quote_and_date(provider_symbol: str, target_date: date, window_days: int = 10) -> Optional[tuple[float, date]]`.

- [ ] **Step 1: Write the failing test for resilient historical lookup on same-day and weekends**

Add tests in `backend/tests/test_api.py` (mocking or testing `_fetch_historical_quote_and_date` with simulated empty DataFrame on start=today, falling back to fast_info or latest close).

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\pytest.exe backend/tests/test_api.py -k "test_historical_quote"`

- [ ] **Step 3: Implement resilient lookback and fallback logic in `backend/api/main.py` and `yahoo_adapter.py`**

1. Look back 10 calendar days up to `target_date + timedelta(days=1)`.
2. Filter for bars on or before `target_date` and select the latest available close.
3. If no bars found (e.g. `target_date >= date.today()` or closed market/weekend), fall back to `fast_info` (`last_price` / `regularMarketPrice` / `previous_close`) or `t.history(period="5d")` last row.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\pytest.exe backend/tests/test_api.py -k "test_historical_quote" -v`

---

### Task 2: Auto-Resolution of Analysis & YTD Metrics on Creation and Single-Row Refresh (Issue 1)

**Files:**
- Modify: `backend/api/main.py:586-750, 1044-1087`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `_fetch_historical_quote_for_date`, `_fetch_start_of_year_quote`.
- Produces: Complete quote and reference price resolution on `POST /api/instruments` and `POST /api/instruments/{ticker}/refresh`.

- [ ] **Step 1: Write the failing test for single-row refresh auto-resolving missing analysis price**

Add test in `backend/tests/test_api.py` verifying that calling `POST /api/instruments/{ticker}/refresh` for an instrument with `analysis_date` but no `analysis_reference_price` populates `analysis_reference_price` in the instrument and returns it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\pytest.exe backend/tests/test_api.py -k "test_refresh_single_resolves_analysis_price"`

- [ ] **Step 3: Update `create_instrument` and `refresh_single` in `backend/api/main.py`**

1. In `create_instrument`: ensure resilient historical lookup resolves `analysis_reference_price` for today's date or given date, resolves `start_of_year_price`, and saves both to SQLite.
2. In `refresh_single`: if `inst.analysis_reference_price` is missing/empty, resolve it from `inst.analysis_date or date.today()`. Save to SQLite and return updated fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\pytest.exe backend/tests/test_api.py -k "test_refresh_single_resolves_analysis_price" -v`

---

### Task 3: Backend Support for Ticker Renaming & Clean Metadata Update (Issue 3 Backend)

**Files:**
- Modify: `backend/api/main.py:294-306, 756-825`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `InstrumentUpdate(new_ticker, company_name, currency, exchange, ...)`
- Produces: Atomically updated instrument and quote records in SQLite without stale name or quotes.

- [ ] **Step 1: Write failing test for ticker rename with currency, exchange, and company name update**

Add test in `backend/tests/test_api.py` testing renaming `BME:SAN` to `AAPL` with new currency USD, new exchange US, and auto-resolved or updated company name.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\venv\Scripts\pytest.exe backend/tests/test_api.py -k "test_update_rename_ticker"`

- [ ] **Step 3: Update `InstrumentUpdate` model and `update_instrument` in `backend/api/main.py`**

1. Add `currency: Optional[str] = None` and `exchange: Optional[str] = None` to `InstrumentUpdate`.
2. In `update_instrument`: when `new_ticker` is provided, update `inst.currency` and `inst.exchange`. If `company_name` is empty or matches old name or AUTO, resolve name from Yahoo or use `new_ticker`. If quote exists, update quote symbol and quote row.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\venv\Scripts\pytest.exe backend/tests/test_api.py -k "test_update_rename_ticker" -v`

---

### Task 4: Frontend UI Updates in `ManualEntryModal.tsx` & `WatchlistTable.tsx` (Issues 1, 2, 3 Frontend)

**Files:**
- Modify: `frontend/components/ManualEntryModal.tsx`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/WatchlistTable.tsx`
- Test: `frontend/scripts/verify_watchlist_fixes.mts`

**Interfaces:**
- Consumes: `checkYahooTicker`, `fetchAnalysisPrice`, `fetchYtdPrice`, `updateInstrument`, `refreshInstrument`.
- Produces:
  - Creation mode without `Precio Ref. Análisis` field.
  - "Confirmar cambio y actualizar datos" button in Edit mode that syncs all metadata.
  - Flushing of old metadata upon ticker change.
  - Instant reactive table update on creation and single-row refresh.

- [ ] **Step 1: Write verification script `frontend/scripts/verify_watchlist_fixes.mts`**

Test contract and logic:
1. Verify Creation mode does not render `addAnalysisPrice` input.
2. Verify Edit mode retains `editAnalysisPrice` input.
3. Verify "Confirmar cambio y actualizar datos" button and handler exist in `ManualEntryModal.tsx`.
4. Verify `updateInstrument` passes `currency` and `exchange` when changed.
5. Verify `refreshSingle` refreshes and syncs state.

- [ ] **Step 2: Run script to verify it fails**

Run: `npx tsx scripts/verify_watchlist_fixes.mts`

- [ ] **Step 3: Implement frontend changes**

1. In `ManualEntryModal.tsx`:
   - In Creation mode: render `Precio Objetivo` and `Fecha de Análisis` in a 2-column grid. Do not render `addAnalysisPrice`.
   - In Edit mode: track `editCurrency` and `editExchange`.
   - In Edit mode ticker validation banner: when `editTicker !== originalTickerToEdit` and `yahooCheckResult?.available`, render an explicit button:
     `<button type="button" onClick={handleConfirmTickerChange} ...>Confirmar cambio y actualizar datos</button>`.
   - Implement `handleConfirmTickerChange`:
     - Overwrite `editCompanyName` with `yahooCheckResult.company_name`.
     - Overwrite `editCurrency` and `editExchange`.
     - Overwrite `editLatestPrice` and `editPrevClose`.
     - Call `fetchAnalysisPrice(editTicker, editAnalysisDate)` and set `editAnalysisPrice`.
     - Call `fetchYtdPrice(editTicker)` and set `editStartOfYearPrice` and `editStartOfYearDate`.
   - In `handleEditSubmit`: pass `currency` and `exchange` to `updateInstrument`.
2. In `WatchlistTable.tsx`:
   - In `handleSingleRefresh`: call `refreshInstrument(ticker)`, notify with toast, and trigger silent reload.

- [ ] **Step 4: Run script to verify it passes**

Run: `npx tsx scripts/verify_watchlist_fixes.mts`

---

### Task 5: Zero-Regression Full Verification

**Files:**
- All tests

- [ ] **Step 1: Run complete backend pytest suite**
Run: `.\venv\Scripts\pytest.exe tests/ backend/tests/ -v`

- [ ] **Step 2: Run complete frontend npm test suite**
Run: `npm test` inside `frontend/`
