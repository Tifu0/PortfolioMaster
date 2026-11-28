# Unit 7 Specification: Frontend Component Modularization, Memoization & Integral Verification Gate

## 1. Objectives & Constraints
- **Scope:** Refactor monolithic frontend components (`WatchlistTable.tsx` at 2,510 lines and `ManualEntryModal.tsx` at 1,398 lines) into cohesive, deep modules and pure TypeScript utilities without breaking any public interfaces, backend contracts, or Unit 6 UX/i18n/accessibility/responsive invariants.
- **Hard Invariants:**
  - Zero edits to backend (`backend/`, `src/`, `alembic/`, `tests/`).
  - Zero new dependencies in `frontend/package.json`.
  - Zero production `localStorage` access outside `frontend/lib/storage.ts`.
  - Zero `fs.readFileSync` / static grep tests in `frontend/scripts/`.
  - Preserve 100% of U6 guarantees: `AuthModal` `z-[150]`, conditional `loadInstruments()` in `ManualEntryModal`, `Toast` placement (`z-[200]`, `aria-live="polite"`), silent unauthenticated `401` handling on `/backup`, `375x812` mobile zero-overflow, `1280x800` 12-column table visibility (`DEFAULT_WATCHLIST_COLUMN_WIDTHS` total `<= 1180px`), `color-scheme: dark`, `<SkipToContentLink />`, `<main id="main-content">`, `role="switch"` + ARIA labels, `overscroll-contain`, `motion-reduce`, and unified typed EN/ES copy in `frontend/lib/translations.ts`.

---

## 2. Target Module Tree

```text
frontend/
├── lib/
│   ├── storage.ts                  # SSR-safe, fault-tolerant localStorage adapter
│   ├── watchlist-formatters.ts     # Pure row-height bounds, column width budget, formatters, sort/filter helpers
│   ├── instrument-constants.ts     # Exchanges, currencies, payload builders, form validators
│   ├── formatters.ts               # Existing currency formatter (unchanged interface)
│   ├── modal-policies.ts           # Existing auth/modal fetch policies (unchanged)
│   └── translations.ts             # Strictly typed EN/ES dictionary (unchanged contract)
├── components/
│   ├── WatchlistTable.tsx          # Thin orchestrator & backwards-compatible re-exports (target <= 450 lines)
│   ├── watchlist/
│   │   ├── WatchlistToolbar.tsx    # Search, filters, customize popover, refresh trigger
│   │   ├── RowHeightPopover.tsx    # Row density selector, quick presets & live preview
│   │   ├── WipeDatabaseModal.tsx   # Accessible destructive confirmation dialog
│   │   ├── WatchlistEmptyState.tsx # Unauthenticated, loading, empty & bottom add row states
│   │   ├── useWatchlistActions.ts  # Optimistic mutations, SSE batch/single refresh & date handlers
│   │   ├── watchlistColumns.tsx    # Typed ColumnDef factory (zero editingDateValue dep)
│   │   ├── InlineDateCell.tsx      # React.memo cell owning local inline date draft state
│   │   └── InstrumentDescriptionPanel.tsx # React.memo expandable notes editor row
│   ├── ManualEntryModal.tsx        # Thin modal shell & backwards-compatible re-exports (target <= 200 lines)
│   └── instrument-modal/
│       ├── AddInstrumentForm.tsx   # Create instrument + Yahoo auto-detect + validation
│       └── EditInstrumentForm.tsx  # Edit/delete/sync instrument + historical/YTD lookups
└── scripts/
    └── test_u7_modular_units.mts   # Pure unit tests for storage, watchlist-formatters, instrument-constants
```

---

## 3. Pure Utility Contracts (`U7.1`)

### 3.1 `frontend/lib/storage.ts`
```ts
export function getStoredString(key: string): string | null;
export function setStoredString(key: string, value: string): boolean;
export function getStoredJson<T>(
  key: string,
  fallback: T,
  validate?: (value: unknown) => value is T
): T;
export function setStoredJson<T>(key: string, value: T): boolean;
export function removeStoredItem(key: string): boolean;
```
- **SSR safety:** Must check `typeof window === 'undefined'` before reading `window.localStorage`, returning `null` / `fallback` / `false` cleanly.
- **Fault tolerance:** Must catch `SecurityError`, `QuotaExceededError`, and `SyntaxError` without throwing, returning `fallback` on invalid JSON or failed validator checks.
- **Consolidated callers:** `WatchlistTable.tsx`, `LanguageContext.tsx`, and `AuthContext.tsx` migrate all `localStorage` calls to `storage.ts`.

### 3.2 `frontend/lib/watchlist-formatters.ts`
- **Constants & helpers (re-exported by `WatchlistTable.tsx`):**
  - `MIN_ROW_HEIGHT = 32`, `DEFAULT_ROW_HEIGHT = 48`, `MAX_ROW_HEIGHT = 88`
  - `ROW_HEIGHT_STORAGE_KEY = 'portfoliomaster_row_height'`
  - `SORTING_STORAGE_KEY = 'portfoliomaster_table_sorting'`
  - `COLUMN_SIZING_STORAGE_KEY = 'portfoliomaster_column_sizing'`
  - `DEFAULT_WATCHLIST_COLUMN_WIDTHS` (sum `1168px <= 1180px`)
  - `clampRowHeight(value: number): number`
  - `getRowCellPaddingClass(rowHeight: number): string`
  - `formatStackedDate(isoDate: string | null | undefined): { dayMonth: string; year: string } | null`
- **Formatting, filtering & sorting:**
  - `formatPercent(value: number | null | undefined, valid: boolean): { text: string; colorClass: string }`
  - `formatDeclineToTarget(value: number | null | undefined, valid: boolean): { text: string; colorClass: string }`
  - `timeAgo(isoDate: string | null | undefined, now: number, t: TranslateFn): string`
  - `getQuoteTooltip(pos: Position, t: TranslateFn, now?: number): string | undefined`
  - `numericSortWithNulls(rowA: { getValue: (id: string) => unknown }, rowB: { getValue: (id: string) => unknown }, columnId: string): number`
  - `filterWatchlistPositions(positions: Position[], filters: { exchange: string; currency: string; query: string }): Position[]`

### 3.3 `frontend/lib/instrument-constants.ts`
- `DEFAULT_EXCHANGE = 'AUTO'`, `DEFAULT_CURRENCY = 'AUTO'`
- `POPULAR_EXCHANGES`, `POPULAR_CURRENCIES`
- `ManualEntryUpdatePayloadInput`, `buildManualEntryUpdatePayload` (re-exported by `ManualEntryModal.tsx`)
- `getTodayLocalDateString(): string`
- `parseOptionalNumber(value: string): number | null` (returns `null` for blank or non-finite values)
- `normalizeTicker(value: string): string` (trims and uppercases)
- `validateAddInstrumentInput(input: { ticker: string; fetchYahoo: boolean; manualPrice?: string; targetPrice?: string }): { valid: boolean; errorKey?: TranslationKey }`
- `validateEditInstrumentInput(input: { ticker: string; targetPrice?: string; analysisPrice?: string; latestPrice?: string }): { valid: boolean; errorKey?: TranslationKey }`

---

## 4. Frozen Public Props & Memoization Boundaries (`U7.2` & `U7.3`)

### 4.1 `WatchlistTable` (`frontend/components/WatchlistTable.tsx`)
```ts
export interface WatchlistTableProps {
  initialPositions: Position[];
  initialMetrics?: PortfolioMetrics | null;
  appConfig?: AppConfig | null;
  onDataChange?: (positions: Position[], metrics: PortfolioMetrics | null) => void;
  onEditTicker?: (ticker: string) => void;
  onAddInstrument?: () => void;
}
```
- **Render optimization invariant:** `WatchlistTable` does **not** store `editingDateValue` state. `columns` (`useMemo`) depends strictly on `[editingDateTicker, updatingDateTickers, handleStartEditingDate, handleCancelEditingDate, handleSaveDate, refreshingTickers, batchRefreshing, handleSingleRefresh, onEditTicker, expandedDescriptionTickers, toggleDescription, language, t]`.
- `InlineDateCell` (`React.memo`) mounts an internal draft state initialized from `analysisDate ?? ''` whenever `isEditing` becomes `true`, keeping keystrokes isolated to that single cell and preventing full-table column rebuilds.
- `InstrumentDescriptionPanel` (`React.memo`) isolates expanded row comment rendering and draft editing.

### 4.2 `ManualEntryModal` (`frontend/components/ManualEntryModal.tsx`)
```ts
export interface ManualEntryModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTickerToEdit?: string | null;
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
}
```
- Thin dialog wrapper preserving `z-[100]`, `overscroll-contain`, `role="dialog"`, `aria-modal="true"`, `aria-labelledby="manual-entry-modal-title"`, and `!isBusy` Escape key guard, delegating body rendering to `<AddInstrumentForm />` or `<EditInstrumentForm />`.

---

## 5. Verification Plan (Spec-TDD)
1. **Red (`Phase B`):** Create `frontend/scripts/test_u7_modular_units.mts` (added to `frontend/package.json`) testing `storage.ts` (SSR `window === undefined`, `SecurityError`, `QuotaExceededError`, corrupt JSON fallback), `watchlist-formatters.ts` (percent, target distance badges, dates, nulls, numeric sorting, position filtering), and `instrument-constants.ts` (ticker normalization, number parsing, add/edit validators, payload builders). Run `npm test` to verify Red failure prior to module creation.
2. **Green (`U7.1` -> parallel `U7.2` + `U7.3` -> `U7.4`):** Implement modules sequentially per boundary, verify `npm run lint`, `npx tsc --noEmit`, `npm test`, and `npm run build`.
3. **E2E (`playwright-cli`) & Full Regression (`U7.4` & `Phase D`):**
   - Headless Chromium E2E across `375x812` & `1280x800` against ephemeral local servers (read-only mock API on `127.0.0.1:8000` + Next.js on `127.0.0.1:3000`): column sorting persistence, `RowHeightPopover` presets, inline date editing / description panel, Wipe modal open/Escape, Add/Edit modal & `AuthModal` stacking, EN/ES toggle, 0 console/hydration errors, and ports closed afterward.
   - Run backend `pytest` suite completely and confirm empty `git diff -- backend/ src/ alembic/ tests/`.
