# Word-Stacked Responsive Column Headers & Global Row Height Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement word-stacked font-scaling responsive column headers allowing narrow `minSize` columns bounded by the longest word in each header title, and a customizable toolbar row height controller (hidden by default) with an interactive 2-row sample live preview, empirical minimum bounds, warning alerts, and `localStorage` persistence.

**Architecture:**
- **Word-Stacked Font-Scaling Headers**: In `frontend/components/WatchlistTable.tsx`, audit all 12 column definitions to establish narrow, longest-word-bounded `minSize` constraints. Replace fixed `truncate` containers in `<th>` with a responsive header component that dynamically scales font size (from `text-xs` down to `9.5px-10px`), tightens line height (`leading-[1.05]`), adjusts horizontal padding, and wraps multi-word titles strictly on word boundaries (`[word-break:keep-all] whitespace-normal`) without vertical character stacking.
- **Global Row Height Controller & Toolbar Customization**: Add `rowHeight: boolean` (default `false`) to `ToolbarConfig`, `DEFAULT_TOOLBAR_CONFIG`, and `TOOLBAR_ITEMS` in `WatchlistTable.tsx`. Add a new toolbar button (`Altura · ${rowHeight}px`) visible only when toggled on.
- **Interactive Row Height Popover with 2-Row Sample Preview**: Implement an interactive popover featuring synchronized slider and numeric inputs (`MIN_ROW_HEIGHT = 32`, `DEFAULT_ROW_HEIGHT = 48`, `MAX_ROW_HEIGHT = 88`), quick reset, an empirical minimum-value warning banner, and an embedded 2-row live preview table with realistic instruments (`AAPL` and `BME:MAP`) responding in real time.
- **Table Density & 60fps CSS Custom Property Application**: Apply `--watchlist-row-height: ${rowHeight}px` to the main table, dynamically adjust `py-*` cell padding to prevent clipping at compact bounds, and persist to `localStorage` (`portfoliomaster_row_height`) with SSR hydration mismatch protection.
- **Automated Verification**: Create `frontend/scripts/verify_responsive_headers_and_row_height.mts` and update `frontend/scripts/verify_toolbar_and_backup_tab.mts`, wire into `npm test`, and verify with browser tests.

**Tech Stack:** Next.js 16 (App Router, React 19), TypeScript, `@tanstack/react-table`, Tailwind CSS v4, Lucide React.

**Spec:** User prompt requirements for Feature 1 (Responsive Headers) and Feature 2 (Row Height Controller).

## Global Constraints
- **Word Wrapping Only**: No vertical character stacking (`writing-mode: vertical-rl` and `word-break: break-all` are strictly forbidden). Multi-word headers must break naturally word by word (`word-break: keep-all; white-space: normal; overflow-wrap: normal;`).
- **Default Toolbar Visibility**: Row Height button must be `false` by default, appearing only when toggled on in the toolbar customization menu.
- **Reset to Defaults Ergonomics**: Clicking `Reset to Defaults` in the toolbar customization popover must reset `rowHeight` visibility to `false` and restore row height to `DEFAULT_ROW_HEIGHT = 48`.
- **Minimum Value Enforcement**: Clamp row height at `MIN_ROW_HEIGHT = 32`. Show an amber warning alert when at or below minimum.
- **SSR Safety**: All `localStorage` reads must run inside `useEffect` or safe client-only checks to avoid hydration mismatches.
- **Test Integrity**: All existing `npm test` checks and new verification tests must pass with 0 errors.

## Review Focus
1. Headers with multi-word titles (`"Último Precio"`, `"Var. Diaria"`, `"Var. YTD"`, `"Var. vs Análisis"`, `"Caída a Objetivo"`, `"P. Objetivo"`) must wrap cleanly word by word on multiple lines without clipping or overlapping sort indicators or resize handles.
2. Single-word titles (`"Ticker"`, `"Empresa"`, `"Mercado"`, `"Divisa"`) and short headers must shrink down to compact widths bounded only by their single longest word and sort icon.
3. Toggling the Row Height option in the toolbar customization popover must show/hide the button, persist to `localStorage`, and hide upon "Reset to Defaults".
4. Dragging the row height slider or entering numbers must update both the 2-row sample preview and the main table instantly with zero lag.
5. Entering <= 32px must clamp to 32px and display the minimum warning message.

---

### Task 1: Audit Column Definitions & Longest-Word-Bounded `minSize`

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx`

**Interfaces:**
- Updates `columns` in `WatchlistTable.tsx` with optimized `minSize` values based on each column's longest word at min legible font size (~10px):
  - `analysis_date`: Title "Fecha Análisis" (longest word "Análisis" = 8 chars), minSize: 56
  - `user_ticker`: Title "Ticker" (longest word "Ticker" = 6 chars), minSize: 70
  - `company_name`: Title "Empresa" (longest word "Empresa" = 7 chars), minSize: 85
  - `exchange`: Title "Mercado" (longest word "Mercado" = 7 chars), minSize: 65
  - `currency`: Title "Divisa" (longest word "Divisa" = 6 chars), minSize: 52
  - `latest_price`: Title "Último Precio" (longest word "Último" = 6 chars), minSize: 76
  - `daily_variation`: Title "Var. Diaria" (longest word "Diaria" = 6 chars), minSize: 68
  - `ytd_variation`: Title "Var. YTD" (longest word "Var." = 4 chars), minSize: 64
  - `variation_since_analysis`: Title "Var. vs Análisis" (longest word "Análisis" = 8 chars), minSize: 78
  - `decline_to_target`: Title "Caída a Objetivo" (longest word "Objetivo" = 8 chars), minSize: 82
  - `target_price`: Title "P. Objetivo" (longest word "Objetivo" = 8 chars), minSize: 75
  - `actions`: size: 105, minSize: 105, enableResizing: false

- [ ] **Step 1: Update column `minSize` values in `WatchlistTable.tsx`**
Update `minSize` in each column definition with the audited longest-word-bounded values.

---

### Task 2: Implement Word-Stacked & Font-Scaling Header Component

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx`

**Interfaces:**
- Produces: Header container in `<th>` that inspects `header.getSize()` to dynamically compute:
  - Font size: >= 110px -> `text-xs` (12px); 85-109px -> `text-[11px]`; < 85px -> `text-[10px]` (minimum legible ~9.5-10px)
  - Horizontal padding on `<th>`: >= 110px -> `px-3.5`; 80-109px -> `px-2.5`; < 80px -> `px-1.5`
  - Line height: tight `leading-[1.08]` for stacked multi-line headers
  - Word wrapping: `whitespace-normal break-normal [word-break:keep-all] [overflow-wrap:normal]` (strictly avoiding `break-all`)
  - Alignment and sort icons: Keep sort icons cleanly positioned (`shrink-0`) without clipping or covering text
  - Resize handle: Positioned with clearance so it never overlaps the stacked words even at `minSize`.

- [ ] **Step 1: Replace `<div className="truncate">` in the `thead` with responsive header renderer**
Ensure the container allows multi-line word wrapping while respecting column width.

- [ ] **Step 2: Update individual column header button layouts**
Ensure button elements allow wrapping `whitespace-normal [word-break:keep-all]` and position sort indicators (`ArrowUp`, `ArrowDown`, `ArrowUpDown`) alongside the text cleanly.

---

### Task 3: Global Row Height Constants, Toolbar Integration & Persistence

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx`

**Interfaces:**
- Exports constants:
  - `MIN_ROW_HEIGHT = 32`
  - `DEFAULT_ROW_HEIGHT = 48`
  - `MAX_ROW_HEIGHT = 88`
  - `ROW_HEIGHT_STORAGE_KEY = 'portfoliomaster_row_height'`
- Updates:
  - `ToolbarConfig` with `rowHeight: boolean`
  - `DEFAULT_TOOLBAR_CONFIG` with `rowHeight: false`
  - `TOOLBAR_ITEMS` with `{ key: 'rowHeight', label: 'Altura de Filas', icon: Rows3, iconColor: 'text-indigo-400' }`
  - Toolbar customization popover handles toggling `rowHeight` and resetting height on `Reset to Defaults`.
  - State `rowHeight` initialized to `DEFAULT_ROW_HEIGHT`, restored from `localStorage` in `useEffect`, with clamp `[MIN_ROW_HEIGHT, MAX_ROW_HEIGHT]`.

- [ ] **Step 1: Add row height constants and update ToolbarConfig types/defaults**
Add constants and update `ToolbarConfig`, `DEFAULT_TOOLBAR_CONFIG`, and `TOOLBAR_ITEMS`.

- [ ] **Step 2: Add row height state and localStorage synchronization**
Add `rowHeight` state, `rowHeightOpen` popover state, and hydration-safe `localStorage` synchronization.

- [ ] **Step 3: Update `handleResetToolbarConfig`**
Ensure resetting toolbar also resets `rowHeight` to `DEFAULT_ROW_HEIGHT` and removes `portfoliomaster_row_height` from `localStorage`.

---

### Task 4: Interactive Row Height Controller Popover & 2-Row Sample Live Preview

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx`

**Interfaces:**
- Produces:
  - Toolbar button: `Altura · ${rowHeight}px` with `Rows3` icon when `toolbarConfig.rowHeight` is enabled.
  - Interactive Popover containing:
    1. Header: "Altura de Filas" + quick `Restablecer (48px)` button + close button.
    2. Slider (`<input type="range" min={32} max={88} ... />`) + synchronized numeric input (`<input type="number" ... />`) with `px` suffix.
    3. Quick preset chips: `Compacto (34px)`, `Estándar (48px)`, `Amplio (64px)`.
    4. Minimum Warning Banner: Displays when `rowHeight <= MIN_ROW_HEIGHT` explaining why smaller values are disabled.
    5. Embedded 2-Row Sample Table Preview:
       - Displays 2 realistic instruments (`AAPL` and `BME:MAP`).
       - Renders with columns: Ticker, Precio, Var. Diaria, Fecha Análisis, Acciones.
       - Rows update live as slider is dragged, demonstrating vertical centering, badge padding, and legibility.

- [ ] **Step 1: Implement the Row Height button in the toolbar**
Render button next to other actions when `toolbarConfig.rowHeight` is true.

- [ ] **Step 2: Build the Row Height popover with slider, numeric input, presets, and minimum warning**
Connect slider and numeric input to `rowHeight` state with clamping and warning condition.

- [ ] **Step 3: Build the embedded 2-row sample table live preview inside the popover**
Render mock rows for `AAPL` and `BME:MAP` with dynamic row height.

---

### Task 5: Apply Dynamic Row Height & Density to Main Watchlist Table

**Files:**
- Modify: `frontend/components/WatchlistTable.tsx`

**Interfaces:**
- Applies `--watchlist-row-height: ${rowHeight}px` to `<table>` style.
- Applies dynamic vertical padding to `<td>` based on current `rowHeight`:
  - `rowHeight <= 34`: `py-1 px-3`
  - `rowHeight <= 42`: `py-2 px-3.5`
  - `rowHeight > 42`: `py-3.5 px-4`
- Body cells use `align-middle overflow-hidden` and `height: var(--watchlist-row-height)`.

- [ ] **Step 1: Bind CSS custom property and dynamic cell padding**
Update table wrapper, `table`, `tr`, and `td` to use dynamic height and padding.

---

### Task 6: Automated Testing, Build & Browser Verification

**Files:**
- Modify: `frontend/scripts/verify_toolbar_and_backup_tab.mts`
- Create: `frontend/scripts/verify_responsive_headers_and_row_height.mts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Update `verify_toolbar_and_backup_tab.mts` to account for `rowHeight: false` default**
- [ ] **Step 2: Create `verify_responsive_headers_and_row_height.mts` script**
Test column minSize bounds, word-wrap classes, row height constants, toolbar toggle, warning banner, and 2-row preview.
- [ ] **Step 3: Update `package.json` test script and run `npm test`**
- [ ] **Step 4: Verify build and visual appearance via Playwright / browser**
