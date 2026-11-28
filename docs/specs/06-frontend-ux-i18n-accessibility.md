# Unit 6 Specification: Frontend UX Fixes, A11y, i18n Unification & Behavioral Testing

## 1. Goals & Scope Boundaries
Unit 6 resolves critical UX defects, mobile/desktop layout regressions, accessibility and dark-mode gaps, fragmented internationalization, and brittle static grep tests across `frontend/`, **without** altering backend Python modules (`backend/`, `src/`, `alembic/`, `tests/`) or introducing external npm dependencies. Component splitting of `WatchlistTable.tsx` and `ManualEntryModal.tsx` remains deferred to Unit 7; edits to those files in Unit 6 are surgical.

---

## 2. Sub-unit U6.1: Modal Stacking, Conditional Network Loads, Toast, 401 Silence & Header Indicator

1. **Modal Layering (`z-index`):**
   - `AuthModal`: backdrop rendered at `z-[150]` (raised from `z-50`), ensuring login/re-auth dialogs always appear above `ManualEntryModal` (`z-[100]`), `WipeDatabaseModal` (`z-[100]`), `BackupExportModal` (`z-[100]`), and table popovers (`z-[100]`).
2. **Conditional Fetch in `ManualEntryModal`:**
   - Opening `ManualEntryModal` in creation mode (`!isEditMode`) or without an authenticated user session (when auth is configured and `user === null`) MUST NOT trigger `api.getInstruments()`. Opening `/?add=1` unauthenticated produces **0** `GET /api/instruments` (`401`) requests and never traps `AuthModal` behind `ManualEntryModal`.
   - Export pure policy helper `shouldLoadInstrumentsOnModalOpen({ isEditMode, isAuthConfigured, isAuthenticated, hasInitialTicker })` in `frontend/lib/modal-policies.ts` so behavior is directly unit-tested.
3. **Non-Intrusive Toast Container & Live Region:**
   - Move `ToastProvider` container from `fixed inset-x-4 top-20` to bottom positioning (`fixed inset-x-4 bottom-4 sm:left-auto sm:right-4 sm:bottom-6 z-[200]` with safe-area bottom margin) so notifications never cover modal headers, close buttons, or sticky `HeaderNav`.
   - Keep a persistent accessible live-region container (`aria-live="polite"`, `aria-atomic="false"`) mounted at root so dynamic toast announcements are reliably spoken by screen readers; keep `overscroll-contain` on toast scroll region and localize its dismiss `aria-label` via `t('toastDismiss')`.
4. **Silent Expected `401` Handling in `BackupExportView`:**
   - Do not emit `console.warn` when `getBackupList()` fails with HTTP `401` (`ApiError` with `status === 401`), and avoid calling `getBackupList()` automatically when auth is configured and `user === null`. Expose a pure guard `isExpectedUnauthenticatedError(err, hasSession)` / skip rule cleanly.
5. **Decision on Decorative `FastAPI` Badge (`AppHeader.tsx`):**
   - **Decision: Retire the decorative `FastAPI` badge** (and remove the dead `fastApiStatus` key from `translations.ts`).
   - **Rationale:** Hardcoding a pulsing green dot labeled `FastAPI` misleads users when offline, leaks backend implementation naming into end-user chrome, consumes scarce horizontal header space at `375px`, and adding background `/api/health` requests from `AppHeader` risks spurious failed network console noise on static/unbacked test environments. Sync/connectivity feedback is already conveyed authentically inside watchlist controls (`WatchlistRefreshBadge`).

---

## 3. Sub-unit U6.2: Responsive Layout (`375x812` & `1280x800`), Native Dark Mode & Accessibility

1. **Mobile (`375x812`) Zero Horizontal Overflow on `/`, `/import`, `/backup`:**
   - Guarantee `document.documentElement.scrollWidth <= window.innerWidth` across all three routes at `375x812` (signed out and with `/?add=1`).
   - `AppHeader`: hide `v1.0` badge below `sm` (`hidden sm:inline-flex`), constrain gaps on `xs` (`gap-2 sm:gap-3`), apply `min-w-0` on flex children.
   - `UserAuthButton`: add `whitespace-nowrap shrink-0` so `Sign In` / `Iniciar sesión` never wraps across two lines; cap email chip width neatly on small screens.
   - `HeaderNav`: add `shrink-0 whitespace-nowrap` on tab `<Link>`s inside `overflow-x-auto`.
   - `WatchlistTable`, `ManualEntryModal`, `ImportView`, `BackupExportView`, and all three `loading.tsx` skeletons: replace fixed `w-96` / oversized popover widths with responsive classes (`max-w-md w-full`, `max-w-[calc(100vw-2rem)]`, `flex-wrap`, `min-w-0`). Keep table empty state visible within viewport width (`sticky left-0` or bounded width wrapper) rather than centered off-screen inside a wide table.
2. **Desktop (`1280x800`) `WatchlistTable` Column Budgets:**
   - Target content container width at `1280px` (`max-w-[1680px]` with `px-8` + borders) is `1214px`.
   - Adjust default compact column sizes in `WatchlistTable.tsx` (while preserving user-resizable overrides in `localStorage`) so the sum of default visible column widths is `<= 1180px`:
     - `analysis_date`: `80`, `user_ticker`: `105`, `company_name`: `165`, `exchange`: `85`, `currency`: `68`, `latest_price`: `105`, `daily_variation`: `95`, `ytd_variation`: `100`, `variation_since_analysis`: `110`, `decline_to_target` (`To Target`): `105`, `target_price` (`Target Price`): `95`, `actions`: `65` -> **Total = `1178px <= 1214px`**.
   - Define these defaults cleanly so both `WatchlistTable` and unit checks verify the column budget (`sum <= 1180px`) without regex-parsing TSX source.
3. **Native Dark Mode & Web Interface Guidelines Compliance:**
   - Set `color-scheme: dark` on `html` in `frontend/app/globals.css` (`colorScheme: 'dark'` metadata/style support) and ensure native `<select>`, `<input type="date">`, `<input type="number">`, and scrollbars render cleanly in dark mode.
   - Add an accessible **Skip to main content** (`<a href="#main-content">`) link as the first focusable element in `layout.tsx` (styled `sr-only focus:not-sr-only ...` with localized label) pointing to `<main id="main-content">` across `/`, `/import`, `/backup`, `loading.tsx`, `error.tsx`, and `not-found.tsx`.
   - Associate explicit `<label htmlFor>` / `aria-label` on the watchlist search box, exchange & currency filters, row height slider/number inputs, comment textarea, inline date editor, file drop inputs, `ManualEntryModal` fields, and `AuthModal` inputs.
   - Add descriptive `aria-label` on all icon-only buttons (`UserAuthButton` sign-out, row actions edit/refresh/delete/comment, modal close buttons, popover triggers, refresh).
   - Convert toolbar settings toggles in `WatchlistTable.tsx` from `<div>` to semantic `<button type="button" role="switch" aria-checked={...}>` operable via `Enter`/`Space` with visible `focus-visible:ring-*`.
   - Convert clickable dropzones / date triggers from clickable `<div>`s to `<button type="button">` or accessible interactive roles with keyboard activation (`Enter`/`Space`).
   - Add `overscroll-contain` (`overscroll-behavior: contain`) and `role="dialog" aria-modal="true"` + `Escape` support consistently on `AuthModal`, `ManualEntryModal`, `BackupExportModal`, and `WipeDatabaseModal`.
   - Add `motion-reduce:animate-none` and `motion-reduce:transition-none` across animated elements, skeletons, and spinners.

---

## 4. Sub-unit U6.3: Strict i18n Unification in `frontend/lib/translations.ts`

1. **Symmetry & Type-Level Guardrail:**
   - `en` defines `export type TranslationKey = keyof typeof enTranslations;`
   - `es` is typed as `const esTranslations: Record<TranslationKey, string> = { ... }` so missing or extra keys fail `npx tsc --noEmit`.
2. **Zero Inline Ternaries & Zero Hardcoded UI Copy:**
   - Migrate all copy in `AppHeader`, `HeaderNav`, `UserAuthButton`, `AuthModal`, `AuthContext` auth prompt message, `MetricCards`, `WatchlistContent`, `WatchlistTable`, `ManualEntryModal`, `ImportView`, `BackupExportView`, `backup/ExportSection`, `backup/RestoreUploadSection`, `backup/LocalSnapshotsSection`, `Toast`, `app/page.tsx`, `app/import/page.tsx`, `app/backup/page.tsx`, `app/error.tsx`, `app/not-found.tsx`, `app/global-error.tsx` (note `global-error.tsx` renders outside `LanguageProvider` so may carry bilingual EN/ES fallback or clean browser-agnostic fallback, and `<html lang={language}>` if practical; all components inside `LanguageProvider` strictly use `t(...)`).
   - Remove every dead key from `translations.ts` so 100% of keys defined in `translations.ts` are actively used in `frontend/`.
   - Replace all misleading UI mentions of `SQLite` (e.g., `/backup` subtitle, `.db` snapshot button/descriptions) with database-agnostic copy accurate for both PostgreSQL multi-tenant mode (JSON snapshot) and local SQLite mode (`.db` snapshot).

---

## 5. Sub-unit U6.4: Script Consolidation Matrix & E2E Plan

All 15 legacy `frontend/scripts/verify_*.mts` scripts map cleanly without retaining any `fs.readFileSync` source-grep tests or pure `tsc` duplicates:

| Legacy Script | Action | Replacement / Destination |
|---|---|---|
| `verify_api_client.mts` | **Keep & trim `typeof` loop** | `frontend/scripts/test_api_client.mts` |
| `verify_batch_auto_sync.mts` | **Keep** | `frontend/scripts/test_refresh_sync.mts` |
| `verify_phase3.mts` | **Extract SSR check, drop literal types** | `frontend/scripts/test_table_ssr_and_budget.mts` |
| `verify_phase6.mts` | **Extract `formatCurrency` behavioral tests, drop `typeof`/`toString()`** | `frontend/scripts/test_formatters_and_metrics.mts` |
| `verify_backup_export.mts` | **Extract SSR modal check, drop literal types** | `frontend/scripts/test_backup_modal_ssr.mts` |
| `verify_phase4.mts` | **Retire (`tsc` + fake inline reduce)** | Real behavioral test on extracted `computeMetricsFromPositions()` in `test_formatters_and_metrics.mts` |
| `verify_phase5.mts` | **Retire (`tsc` duplicate)** | Covered by `tsc --noEmit` + Playwright `/import` |
| `verify_api_cache.mts` | **Replace grep with fetch mock** | Mock `globalThis.fetch` for `getConfig`/`checkYahooTicker` (`cache: 'no-store'`) + `next.config` check in `test_api_client.mts` |
| `verify_phase7.mts` | **Retire (grep)** | Covered by `next build` + Playwright E2E (`/`, `/import`, `/backup`, SEO routes) |
| `verify_toolbar_and_backup_tab.mts` | **Retire (grep + artificial exports)** | Remove unused exports in `WatchlistTable.tsx`; verify toolbar settings & `/backup` in Playwright E2E |
| `verify_portfolio_context.mts` | **Retire (grep)** | Pure unit test of extracted tenant/optimistic state helpers or `PortfolioContext` logic + Playwright sync |
| `verify_watchlist_fixes.mts` | **Retire (grep)** | Pure unit test of `buildManualEntryUpdatePayload` + Playwright modal E2E |
| `verify_analysis_date_column.mts` | **Retire (grep)** | Unit test `formatStackedDate` & column budget + Playwright inline edit E2E |
| `verify_responsive_headers_and_row_height.mts` | **Retire (grep + artificial exports)** | Remove unused exports; unit test row-height clamping/column budget (`<= 1180px`) + Playwright `375x812`/`1280x800` |
| `verify_save_and_update_analysis_date.mts` | **Retire (grep + local mock copy)** | Real unit test calling `buildManualEntryUpdatePayload` + Playwright E2E |
| *(New U6 behavioral guard)* | **Add** | `frontend/scripts/test_i18n_and_policies.mts`: runtime EN/ES translation key parity, non-empty strings, unused-key check, `shouldLoadInstrumentsOnModalOpen`, and `shouldSuppressUnauthWarning` |

- Live `playwright-cli` E2E verification runs read-only against local `next start` / local test server across:
  1. `375x812` (`/`, `/import`, `/backup`): zero horizontal overflow, single-line `Sign In`, `/?add=1` emits zero `401` `/api/instruments` fetches, Toast does not cover modal controls.
  2. `1280x800` (`/`): `To Target`, `Target Price`, `Actions` columns visible in table without mandatory horizontal scroll.
  3. Interactive EN <-> ES toggle across `/`, `/import`, `/backup`: `MetricCards`, headings, buttons, and backup descriptions translate cleanly with zero `SQLite` UI copy.
  4. A11y & console verification: `color-scheme: dark`, skip link + `<main id="main-content">`, `role="switch"`, `aria-label`s, zero `pageerror`, zero hydration mismatch, zero `401` `console.warn` on `/backup`.
