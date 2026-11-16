# Watchlist Table UI Refinement & Inline Analysis Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up Watchlist table rows by removing contextual reference sub-labels beneath YTD and Analysis variations, and add a first column for Analysis Date with single-click inline editing, keyboard/blur handling, background auto-refresh safeguard, and automatic backend price recalculation via Yahoo Finance.

**Architecture:**
- **Frontend Column Cleanup**: In `frontend/components/WatchlistTable.tsx`, simplify `ytd_variation` and `variation_since_analysis` cells to only render the main percentage badge, eliminating secondary reference sub-labels and reducing vertical row height.
- **Frontend Analysis Date Column**: Insert a new `analysis_date` column at index 0 (left of `user_ticker`) with column sizing (`size: 130`, `minSize: 110`), sorting toggle with graceful null handling, and integration with `localStorage` column sizing persistence and the `Restore Columns` button.
- **Inline Editing & Synchronization**: Implement single-click inline date editor with `<input type="date" />`, `Enter`/`Escape`/`onBlur` interactions, auto-refresh safeguard (preserving input during background sync), optimistic UI update, `PUT /api/instruments/{ticker}` update, and chained `POST /api/instruments/{ticker}/fetch-analysis-price` lookup with subtle row/cell spinner.
- **Testing & Verification**: Create `frontend/scripts/verify_analysis_date_column.mts`, hook into `npm test` in `frontend/package.json`, update `README.md`, and run both `npm test` and `pytest`.

**Tech Stack:** Next.js 16 (React 19 App Router), TypeScript, `@tanstack/react-table`, Tailwind CSS v4, FastAPI, SQLite, `yfinance`.

**Spec:** User prompt requirements covering Requirements 1, 2, 3, and 4.

## Global Constraints
- Preserve zero-F5 reactive updates via `PortfolioContext.refreshPortfolioData`.
- Background auto-refresh loop (`REFRESH_INTERVAL_SECONDS`) must NEVER overwrite or close the active inline date editor while typing/picking.
- Zero layout shift when toggling between date text and inline input.
- Maintain full compatibility with `localStorage` column resizing and the `Restore Columns` toolbar action.
- All frontend tests (`npm test`) and backend tests (`pytest` in venv) must pass with 0 errors.

## Review Focus
1. Cell click on `analysis_date` must immediately activate native date editing with a single click.
2. Clicking outside (`onBlur`) or pressing `Enter` with a modified date must commit the change, call `updateInstrument`, and chain `fetchAnalysisPrice`.
3. Pressing `Escape` must immediately cancel editing and revert to the previous value without network calls.
4. Auto-refresh firing in the background while the date input is focused must not reset or unmount the input.
5. `Var. YTD` and `Var. vs Analysis` cells must no longer render secondary price or date sub-labels.

---

### Task 1: Remove Reference Sub-labels in Variation Columns

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx:1100-1175`

**Interfaces:**
- Consumes: `row.original.ytd_variation`, `row.original.ytd_variation_valid`, `row.original.variation_since_analysis`, `row.original.variation_since_analysis_valid`.
- Produces: Clean, compact cells rendering only `formatPercent(...)` badges without reference sub-labels.

- [ ] **Step 1: Simplify `ytd_variation` cell renderer**
Remove `pos.start_of_year_price` and `pos.start_of_year_date` secondary text. Render a single flex container with `text` and `colorClass`.

- [ ] **Step 2: Simplify `variation_since_analysis` cell renderer**
Remove `pos.analysis_reference_price` and `pos.analysis_date` sub-labels / buttons. Render a single flex container with `text` and `colorClass`.

- [ ] **Step 3: Verify clean row height visually / structurally**
Check that row content does not retain nested sub-label `span` elements.

---

### Task 2: Add `Analysis Date` Column at Index 0 with Sorting & Sizing

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx:885-930`

**Interfaces:**
- Consumes: `Position.analysis_date`.
- Produces: First column `analysis_date` with `accessorKey: 'analysis_date'`, `size: 130`, `minSize: 110`, sort header (`ArrowUp`, `ArrowDown`, `ArrowUpDown`), and graceful date sorting comparator.

- [ ] **Step 1: Define `analysis_date` column definition**
Add as index 0 in the `columns` memo array in `WatchlistTable.tsx`.
Configure `size: 130`, `minSize: 110`, `maxSize: 220`, and `enableSorting: true`.
Sorting logic: compare dates formatted as ISO `YYYY-MM-DD`, with null/empty values sorting last in both directions.

- [ ] **Step 2: Verify column sizing and reset integration**
Ensure `handleResetColumnWidths` resets `analysis_date` width alongside other columns when `portfoliomaster_column_sizing` is cleared.

---

### Task 3: Single-Click Inline Date Editor & Auto-Refresh Safeguard

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx`

**Interfaces:**
- Consumes: `updateInstrument` and `fetchAnalysisPrice` from `@/lib/api`, `usePortfolio` optimistic updates.
- Produces: Inline date editor state (`editingDateTicker`, `editingDateValue`, `updatingDateTickers`), keyboard/blur event handlers, and chained price lookup.

- [ ] **Step 1: Add inline editing states and auto-refresh protection**
Add `editingDateTicker: string | null`, `editingDateValue: string`, and `updatingDateTickers: Set<string>`.
Ensure background auto-refresh does not clobber `editingDateValue` or reset `editingDateTicker`.

- [ ] **Step 2: Implement single-click inline cell renderer**
In `analysis_date` column cell:
If `editingDateTicker === pos.user_ticker`, render `<input type="date" />` with `autoFocus`, `onKeyDown`, `onChange`, `onBlur`.
If not editing, render date display with click handler, hover styles, and subtle loading indicator if `updatingDateTickers.has(pos.user_ticker)`.

- [ ] **Step 3: Implement keyboard and blur handling**
`Escape`: cancel and reset `editingDateTicker`.
`Enter`: commit edit if changed.
`onBlur`: commit edit if changed, or simply close if unchanged.

- [ ] **Step 4: Implement backend sync and price recalculation**
When date is committed and changed:
1. Apply optimistic update via `portfolioContext.optimisticUpdatePosition(ticker, { analysis_date: newDate || null })`.
2. Call `updateInstrument(ticker, { analysis_date: newDate || null })`.
3. If `newDate` is provided, call `fetchAnalysisPrice(ticker, newDate)` to update `analysis_reference_price` in backend.
4. Refresh portfolio data via `portfolioContext.refreshPortfolioData({ silent: true })` or `reloadData()`.
5. Show appropriate toast notifications on success or error.

---

### Task 4: Documentation and Automated Verification Test Suites

**Files:**
- Create: `frontend/scripts/verify_analysis_date_column.mts`
- Modify: `frontend/package.json:10`
- Modify: `README.md`

**Interfaces:**
- Consumes: Test script runner (`tsx`).
- Produces: Automated verification suite asserting column order, sub-label removal, inline editing handlers, and documentation updates.

- [ ] **Step 1: Create `frontend/scripts/verify_analysis_date_column.mts`**
Write assertions checking:
1. `WatchlistTable.tsx` defines `analysis_date` as the first column with sorting and sizing.
2. Reference sub-labels are removed from YTD and Analysis columns.
3. Inline editing states and handlers (`updateInstrument`, `fetchAnalysisPrice`, `Escape`, `Enter`, `onBlur`) are wired.
4. Sorting gracefully handles empty dates.

- [ ] **Step 2: Add test script to `frontend/package.json`**
Append `&& tsx scripts/verify_analysis_date_column.mts` to `"test"` in `frontend/package.json`.

- [ ] **Step 3: Update `README.md`**
Update feature description for Watchlist Table to document the new `Analysis Date` column, single-click inline editing, and the compact row layout.

- [ ] **Step 4: Run full test suites**
Run `npm test` in `frontend/` and `.\venv\Scripts\pytest` in root.
Confirm all suites pass with 0 failures.
