import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import {
  DEFAULT_TOOLBAR_CONFIG,
  MIN_ROW_HEIGHT,
  DEFAULT_ROW_HEIGHT,
  MAX_ROW_HEIGHT,
  ROW_HEIGHT_STORAGE_KEY,
  SORTING_STORAGE_KEY,
} from '../components/WatchlistTable';

console.log('Testing Word-Stacked Responsive Headers & Global Row Height Controller...');

// 1. Verify Row Height Constants & Storage Keys
if (MIN_ROW_HEIGHT !== 32) {
  console.error(`❌ MIN_ROW_HEIGHT expected 32, got ${MIN_ROW_HEIGHT}`);
  process.exit(1);
}
if (DEFAULT_ROW_HEIGHT !== 48) {
  console.error(`❌ DEFAULT_ROW_HEIGHT expected 48, got ${DEFAULT_ROW_HEIGHT}`);
  process.exit(1);
}
if (MAX_ROW_HEIGHT !== 88) {
  console.error(`❌ MAX_ROW_HEIGHT expected 88, got ${MAX_ROW_HEIGHT}`);
  process.exit(1);
}
if (ROW_HEIGHT_STORAGE_KEY !== 'portfoliomaster_row_height') {
  console.error(`❌ ROW_HEIGHT_STORAGE_KEY expected "portfoliomaster_row_height", got ${ROW_HEIGHT_STORAGE_KEY}`);
  process.exit(1);
}
if (SORTING_STORAGE_KEY !== 'portfoliomaster_table_sorting') {
  console.error(`❌ SORTING_STORAGE_KEY expected "portfoliomaster_table_sorting", got ${SORTING_STORAGE_KEY}`);
  process.exit(1);
}
console.log('✅ Row height constants, row height storage key, and sorting storage key verified');

// 2. Verify Toolbar Configuration Defaults & Hidden-by-Default Row Height
if (DEFAULT_TOOLBAR_CONFIG.rowHeight !== false) {
  console.error(`❌ DEFAULT_TOOLBAR_CONFIG.rowHeight must be false by default, got ${DEFAULT_TOOLBAR_CONFIG.rowHeight}`);
  process.exit(1);
}
console.log('✅ Row Height button is strictly false (hidden by default) in DEFAULT_TOOLBAR_CONFIG');

// 3. Inspect WatchlistTable.tsx source code for column minSize definitions and word-stacking
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const tablePath = path.resolve(__dirname, '../components/WatchlistTable.tsx');
const tableContent = fs.readFileSync(tablePath, 'utf-8');

// Check word-stacking rules (NO break-all or vertical-rl allowed)
if (tableContent.includes('break-all')) {
  console.error('❌ Found forbidden "break-all" in WatchlistTable.tsx — headers must wrap word-by-word only');
  process.exit(1);
}
if (tableContent.includes('writing-mode: vertical-rl') || tableContent.includes('vertical-rl')) {
  console.error('❌ Found forbidden vertical-rl in WatchlistTable.tsx — vertical character stacking is prohibited');
  process.exit(1);
}
if (!tableContent.includes('[word-break:keep-all]') || !tableContent.includes('whitespace-normal')) {
  console.error('❌ WatchlistTable.tsx missing [word-break:keep-all] or whitespace-normal word-wrapping rules');
  process.exit(1);
}
console.log('✅ Word-wrapping rules verified: strictly preserves word boundaries ([word-break:keep-all], whitespace-normal; no break-all or vertical-rl)');

// Verify Column minSize values are bounded by the longest word and allow narrow resizing
const expectedMinSizes: Record<string, number> = {
  analysis_date: 70,
  user_ticker: 70,
  company_name: 85,
  exchange: 65,
  currency: 52,
  latest_price: 76,
  daily_variation: 70,
  ytd_variation: 64,
  variation_since_analysis: 80,
  decline_to_target: 82,
  target_price: 76,
  actions: 105,
};

let totalAuditedMinSize = 0;
for (const [col, expectedMin] of Object.entries(expectedMinSizes)) {
  const colRegex = new RegExp(`accessorKey:\\s*['"]${col}['"][\\s\\S]*?minSize:\\s*(\\d+)`);
  const match = tableContent.match(colRegex);
  if (match) {
    const actualMin = parseInt(match[1], 10);
    if (actualMin !== expectedMin) {
      console.error(`❌ Column ${col} minSize expected ${expectedMin}, got ${actualMin}`);
      process.exit(1);
    }
    totalAuditedMinSize += actualMin;
  } else {
    // Check if it's actions or decline_to_target
    const idRegex = new RegExp(`id:\\s*['"]${col}['"][\\s\\S]*?minSize:\\s*(\\d+)`);
    const idMatch = tableContent.match(idRegex);
    if (!idMatch) {
      console.error(`❌ Could not find minSize for column ${col}`);
      process.exit(1);
    }
    const actualMin = parseInt(idMatch[1], 10);
    if (actualMin !== expectedMin) {
      console.error(`❌ Column ${col} minSize expected ${expectedMin}, got ${actualMin}`);
      process.exit(1);
    }
    totalAuditedMinSize += actualMin;
  }
}

if (totalAuditedMinSize > 900) {
  console.error(`❌ Total compact table minSize too wide: ${totalAuditedMinSize}px (should be <= 900px)`);
  process.exit(1);
}
console.log(`✅ All 12 columns audited with longest-word-bounded minSizes (total compact width: ${totalAuditedMinSize}px, down from 1220px)`);

// 4. Verify Row Height Controller Popover & 2-Row Sample Live Preview
if (!tableContent.includes('toolbarConfig.rowHeight')) {
  console.error('❌ toolbarConfig.rowHeight button condition missing');
  process.exit(1);
}
if (!tableContent.includes('rowHeightOpen') || !tableContent.includes('handleRowHeightChange')) {
  console.error('❌ rowHeightOpen or handleRowHeightChange missing');
  process.exit(1);
}
if (!tableContent.includes('type="range"') || !tableContent.includes('type="number"')) {
  console.error('❌ Slider (type="range") or numeric input (type="number") missing in row height popover');
  process.exit(1);
}
if (!tableContent.includes('Altura mínima alcanzada') || !tableContent.includes('MIN_ROW_HEIGHT')) {
  console.error('❌ Minimum height warning notice missing in row height popover');
  process.exit(1);
}
if (!tableContent.includes('AAPL') || !tableContent.includes('BME:MAP')) {
  console.error('❌ 2-row sample live preview with AAPL and BME:MAP missing in row height popover');
  process.exit(1);
}
if (!tableContent.includes('--watchlist-row-height')) {
  console.error('❌ CSS custom property --watchlist-row-height missing on table');
  process.exit(1);
}
if (!tableContent.includes('cellPaddingClass')) {
  console.error('❌ Dynamic cellPaddingClass calculation missing');
  process.exit(1);
}
if (!tableContent.includes('handleSortingChange') || !tableContent.includes('onSortingChange: handleSortingChange')) {
  console.error('❌ Sorting persistence mechanism missing in WatchlistTable');
  process.exit(1);
}
console.log('✅ Row height popover verified: slider + numeric input, min-value warning, 2-row live preview (AAPL & BME:MAP), CSS variable binding, and table sorting persistence');

console.log('All Word-Stacked Responsive Headers & Row Height Controller tests passed successfully! 🚀');
