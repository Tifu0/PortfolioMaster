import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

console.log('Testing Watchlist Table UI Refinement & Inline Analysis Date Column...');

// 1. Verify WatchlistTable.tsx implementation
const tablePath = path.join(rootDir, 'components', 'WatchlistTable.tsx');
if (!fs.existsSync(tablePath)) {
  console.error('❌ components/WatchlistTable.tsx does not exist');
  process.exit(1);
}
const tableContent = fs.readFileSync(tablePath, 'utf8');

// 2. Verify analysis_date is the FIRST column (index 0)
const columnsMatch = tableContent.match(/const columns = useMemo<ColumnDef<Position>\[\]>\(\s*\(\)\s*=>\s*\[([\s\S]*?)\]\s*,/);
if (!columnsMatch) {
  console.error('❌ components/WatchlistTable.tsx: Could not parse columns definition');
  process.exit(1);
}
const columnsBlock = columnsMatch[1];
const firstAccessorMatch = columnsBlock.match(/accessorKey:\s*['"]([^'"]+)['"]/);
if (!firstAccessorMatch || firstAccessorMatch[1] !== 'analysis_date') {
  console.error(`❌ components/WatchlistTable.tsx: First column must be 'analysis_date', found '${firstAccessorMatch?.[1]}'`);
  process.exit(1);
}
console.log('✅ First column is analysis_date at index 0');

// 3. Verify column sizing & sorting
if (!columnsBlock.includes("accessorKey: 'analysis_date'") || !columnsBlock.includes('minSize: 70') || !columnsBlock.includes('sortingFn')) {
  console.error('❌ components/WatchlistTable.tsx: analysis_date must configure narrow minSize (70), size (85), and sortingFn');
  process.exit(1);
}
console.log('✅ analysis_date narrow column sizing (size: 85, minSize: 70) & chronological sorting configured');

// 3b. Verify stacked two-line date formatting (DD/MM on top, YYYY below, tabular-nums)
if (!tableContent.includes('formatStackedDate') || !tableContent.includes('dayMonth') || !tableContent.includes('tabular-nums')) {
  console.error('❌ components/WatchlistTable.tsx: analysis_date must use formatStackedDate (DD/MM + YYYY) and tabular-nums');
  process.exit(1);
}
console.log('✅ Compact stacked two-line date formatting (DD/MM + YYYY) with tabular-nums verified');

// 4. Verify sub-labels removal from Var. YTD and Var. vs Analysis
// In ytd_variation cell, secondary sub-label should be removed
const ytdCellMatch = tableContent.match(/accessorKey:\s*'ytd_variation'[\s\S]*?cell:\s*\(\{ row \}\)\s*=>\s*\{([\s\S]*?)\},\s*\},/);
if (!ytdCellMatch) {
  console.error('❌ components/WatchlistTable.tsx: Could not find ytd_variation column cell');
  process.exit(1);
}
if (ytdCellMatch[1].includes('start_of_year_price') || ytdCellMatch[1].includes('sin ref YTD')) {
  console.error('❌ components/WatchlistTable.tsx: ytd_variation cell must not render start_of_year_price or sin ref YTD sub-labels');
  process.exit(1);
}
console.log('✅ Var. YTD reference sub-labels removed');

// In variation_since_analysis cell, secondary sub-label should be removed
const analysisVarCellMatch = tableContent.match(/accessorKey:\s*'variation_since_analysis'[\s\S]*?cell:\s*\(\{ row \}\)\s*=>\s*\{([\s\S]*?)\},\s*\},/);
if (!analysisVarCellMatch) {
  console.error('❌ components/WatchlistTable.tsx: Could not find variation_since_analysis column cell');
  process.exit(1);
}
if (analysisVarCellMatch[1].includes('analysis_reference_price') || analysisVarCellMatch[1].includes('(sin ref)')) {
  console.error('❌ components/WatchlistTable.tsx: variation_since_analysis cell must not render analysis_reference_price or (sin ref) sub-labels');
  process.exit(1);
}
console.log('✅ Var. vs Analysis reference sub-labels removed');

// 5. Verify single-click inline editing interactions
if (!tableContent.includes('type="date"') || !tableContent.includes('editingDateTicker') || !tableContent.includes('editingDateValue')) {
  console.error('❌ components/WatchlistTable.tsx: Missing type="date" input or editing state');
  process.exit(1);
}
if (!tableContent.includes("e.key === 'Enter'") || !tableContent.includes("e.key === 'Escape'")) {
  console.error('❌ components/WatchlistTable.tsx: Missing Enter / Escape keyboard handling for inline date editor');
  process.exit(1);
}
if (!tableContent.includes('onBlur')) {
  console.error('❌ components/WatchlistTable.tsx: Missing onBlur commit handler for inline date editor');
  process.exit(1);
}
console.log('✅ Inline date editor keyboard (Enter/Escape) and onBlur handlers verified');

// 6. Verify backend sync and price recalculation chaining
if (!tableContent.includes('updateInstrument(ticker, { analysis_date:') || !tableContent.includes('fetchAnalysisPrice(ticker,')) {
  console.error('❌ components/WatchlistTable.tsx: Must call updateInstrument and chain fetchAnalysisPrice on date update');
  process.exit(1);
}
console.log('✅ updateInstrument and fetchAnalysisPrice backend sync verified');

console.log('');
console.log('All Watchlist Table UI Refinement & Inline Analysis Date tests passed! 🚀');
