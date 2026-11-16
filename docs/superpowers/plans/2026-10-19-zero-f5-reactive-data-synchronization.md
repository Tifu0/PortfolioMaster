# Zero-F5 Reactive Data Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a Zero-F5 reactive state synchronization architecture across Next.js 16 App Router, React 19, and @tanstack/react-table for PortfolioMaster so all data mutations immediately reflect in the UI without page reloads, flickers, or stale caching.

**Architecture:** A centralized React 19 `PortfolioProvider` at the root layout holding `positions`, `metrics`, and `config` with silent parallel background refreshes (`Promise.allSettled`), instant optimistic UI for deletions and edits with rollback, stable TanStack row identities (`getRowId`), and cross-route synchronization for CSV/Excel imports, backup restores, and database wipes.

**Tech Stack:** Next.js 16 (App Router), React 19 (`use`, `startTransition`, `createContext`), TypeScript 5, @tanstack/react-table 8.

**Spec:** User request: Zero-F5 reactive state architecture, eliminate stale caching, seamless background auto-refresh, instant optimistic updates.

## Global Constraints

- Never unmount `WatchlistTable` or flash full-page loading skeletons during background refreshes.
- Preserve @tanstack/react-table active sorting, search filter, column widths, and scroll position during updates.
- All GET requests in `frontend/lib/api.ts` must explicitly pass `cache: 'no-store'` with no-cache headers.
- All existing tests in `frontend/scripts/verify_*.mts` and backend `pytest` must continue to pass with 0 regressions.
- Comply with React 19 and Next.js 16 App Router best practices (composition, no prop-drilling, `use()`, `force-dynamic`).

## Review Focus

1. `WatchlistTable` re-rendering when data updates: verify TanStack table receives fresh rows without resetting sort or column sizing.
2. Cross-route state consistency: verify navigating between `/`, `/import`, and `/backup` immediately shows current data without F5.
3. Optimistic delete rollback: verify that if `deleteInstrument` fails, the removed row is restored and an error toast is displayed.
4. Auto-refresh non-intrusiveness: verify periodic timer does not interrupt open modals or text input in comments.
5. Verification suite integrity: verify `npm test` and `pytest` run cleanly with all checks green.

---

### Task 1: Eliminate Stale Caching in API Client and App Router

**Files:**
- Modify: `frontend/lib/api.ts:50-310`
- Modify: `frontend/app/page.tsx:1-20`
- Test: `frontend/scripts/verify_api_cache.mts`

**Interfaces:**
- Consumes: `API_BASE_URL` from `frontend/lib/api.ts`
- Produces: Guaranteed `cache: 'no-store'` and `Cache-Control: 'no-cache, no-store'` across `getPositions`, `getInstruments`, `getInstrument`, `getMetrics`, `getConfig`, `checkYahooTicker`, `getBackupList`.

- [ ] **Step 1: Write the verification test for no-store caching**

```typescript
// frontend/scripts/verify_api_cache.mts
import * as api from '../lib/api';
import fs from 'fs';
import path from 'path';

console.log('Testing API Client no-store caching...');
const apiContent = fs.readFileSync(path.resolve('lib/api.ts'), 'utf-8');
if (!apiContent.includes("getConfig(): Promise<AppConfig> {\n  const res = await fetch(`${API_BASE_URL}/api/config`, {\n    cache: 'no-store'")) {
  // check for cache: 'no-store' in getConfig
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test` or `npx tsx scripts/verify_api_cache.mts`
Expected: FAIL indicating missing `no-store` in `getConfig` and `checkYahooTicker`.

- [ ] **Step 3: Update `frontend/lib/api.ts` and `frontend/app/page.tsx`**

Add `cache: 'no-store'` and no-cache headers to `getConfig` and `checkYahooTicker`. Add `export const dynamic = 'force-dynamic'` and `export const revalidate = 0` to `frontend/app/page.tsx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx scripts/verify_api_cache.mts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/app/page.tsx frontend/scripts/verify_api_cache.mts
```

---

### Task 2: Implement Centralized Reactive Portfolio State (`PortfolioProvider`)

**Files:**
- Create: `frontend/context/PortfolioContext.tsx`
- Modify: `frontend/app/layout.tsx:1-40`
- Test: `frontend/scripts/verify_portfolio_context.mts`

**Interfaces:**
- Consumes: `getPositions`, `getMetrics`, `getConfig` from `frontend/lib/api.ts`
- Produces: `PortfolioProvider`, `usePortfolio()`, `refreshPortfolioData()`, `optimisticDelete()`, `optimisticUpdatePosition()`

- [ ] **Step 1: Write verification test for `PortfolioContext`**

Test that `PortfolioProvider` and `usePortfolio` are exported, interface types match, and helper functions exist.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx scripts/verify_portfolio_context.mts`
Expected: FAIL with module not found.

- [ ] **Step 3: Implement `frontend/context/PortfolioContext.tsx` and integrate into `frontend/app/layout.tsx`**

Implement `PortfolioProvider` with:
- State: `positions`, `metrics`, `config`, `isRefreshing`, `lastRefreshedAt`
- `refreshPortfolioData({ silent?: boolean })` using `Promise.allSettled`
- `optimisticDelete(ticker)` returning rollback
- `optimisticUpdatePosition(ticker, updates)` returning rollback
- Non-blocking router refresh via `startTransition(() => router.refresh())`
- Auto-refresh background interval based on `config.refresh_interval_seconds`

Wrap `{children}` in `frontend/app/layout.tsx` with `<PortfolioProvider>`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx scripts/verify_portfolio_context.mts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/context/PortfolioContext.tsx frontend/app/layout.tsx frontend/scripts/verify_portfolio_context.mts
```

---

### Task 3: Connect `WatchlistContent` and `WatchlistTable` to Reactive Portfolio State

**Files:**
- Modify: `frontend/components/WatchlistContent.tsx:60-220`
- Modify: `frontend/components/WatchlistTable.tsx:455-850`
- Test: `npx tsx scripts/verify_phase6.mts`

**Interfaces:**
- Consumes: `usePortfolio()` from `frontend/context/PortfolioContext.tsx`
- Produces: Re-renders `WatchlistTable` smoothly upon `positions` changes without state reset, maintains `getRowId: (row) => row.user_ticker`.

- [ ] **Step 1: Write test verifying reactivity contract for `WatchlistTable` and `WatchlistContent`**

Verify that `WatchlistTable` accepts updated data from context or props and maintains row stability.

- [ ] **Step 2: Update `WatchlistContent.tsx`**

Synchronize `positions` and `metrics` with `usePortfolio()`:
- Use context's `positions`, `metrics`, `appConfig`, `refreshPortfolioData`.
- Seed context with `initialPositions`, `initialMetrics`, `initialConfig` on initial mount if context is empty.

- [ ] **Step 3: Update `WatchlistTable.tsx`**

- Use `positions` from `usePortfolio()` (falling back to prop `initialPositions` for backward compatibility with tests).
- Set `getRowId: (row) => row.user_ticker` in `useReactTable` to ensure stable row identity across background refreshes without losing scroll position or focus.
- Wire `handleBatchRefresh`, `handleSingleRefresh`, `handleResolveAnalysisPrices`, and `handleWipeDatabase` to `refreshPortfolioData()`.
- Use `optimisticUpdatePosition` for inline comment saving.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/components/WatchlistContent.tsx frontend/components/WatchlistTable.tsx
```

---

### Task 4: Instant Optimistic Updates & Deletion in `ManualEntryModal`

**Files:**
- Modify: `frontend/components/ManualEntryModal.tsx:460-500`
- Test: `frontend/scripts/verify_phase7.mts`

**Interfaces:**
- Consumes: `optimisticDelete`, `refreshPortfolioData` from `usePortfolio()`
- Produces: Instant removal from table when delete is confirmed, automatic rollback if API rejects.

- [ ] **Step 1: Verify current `ManualEntryModal` delete logic**

Examine `handleDeleteInstrument` and modal confirmation.

- [ ] **Step 2: Implement optimistic delete and silent refresh in `ManualEntryModal.tsx`**

- When user confirms deletion, immediately call `optimisticDelete(targetTicker)`.
- If `deleteInstrument` throws, execute rollback callback and display error toast.
- If successful, trigger `refreshPortfolioData({ silent: true })` and close modal.
- On creation or update (`handleSaveManual` / `handleSaveEdit`), invoke `refreshPortfolioData({ silent: true })`.

- [ ] **Step 3: Run tests to verify**

Run: `npm test`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/components/ManualEntryModal.tsx
```

---

### Task 5: Cross-Route Synchronization for `ImportView`, `BackupExportView`, and `BackupExportModal`

**Files:**
- Modify: `frontend/components/ImportView.tsx:90-130`
- Modify: `frontend/components/BackupExportView.tsx:170-220`
- Modify: `frontend/components/BackupExportModal.tsx:120-170`
- Test: `frontend/scripts/verify_backup_export.mts` and `frontend/scripts/verify_phase5.mts`

**Interfaces:**
- Consumes: `refreshPortfolioData`, `usePortfolio`
- Produces: Instant cache invalidation and background re-fetching after import confirmation, local snapshot restore, and uploaded backup restore.

- [ ] **Step 1: Verify current import and backup restore handlers**

Trace actions on completion.

- [ ] **Step 2: Wire `refreshPortfolioData()` and `router.refresh()` in `ImportView.tsx`**

After `confirmImport` completes, call `await refreshPortfolioData()` and `router.refresh()`.

- [ ] **Step 3: Wire `refreshPortfolioData()` and `router.refresh()` in `BackupExportView.tsx` & `BackupExportModal.tsx`**

After `restoreBackupFile` and `restoreLocalBackup` complete, call `await refreshPortfolioData()` and `router.refresh()`.

- [ ] **Step 4: Run tests to verify**

Run: `npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/components/ImportView.tsx frontend/components/BackupExportView.tsx frontend/components/BackupExportModal.tsx
```

---

### Task 6: Full Verification and Regression Testing

**Files:**
- Modify: `frontend/package.json:10` (include new verification script if needed)
- Test: `npm test` in `frontend/` and `pytest` in root

- [ ] **Step 1: Run frontend test suite (`npm test`)**

Run: `npm test`
Expected: All verification scripts pass with 0 errors.

- [ ] **Step 2: Run backend test suite (`pytest`)**

Run: `.\venv\Scripts\pytest`
Expected: 72 tests pass with 0 failures.

- [ ] **Step 3: Final sanity check on TypeScript compilation**

Run: `npx tsc --noEmit`
Expected: 0 type errors.
