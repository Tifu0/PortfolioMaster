import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

console.log('Testing Watchlist Manual Entry, Ticker Rename & Historical Resolution Fixes...');

// 1. Verify types.ts contracts
const typesPath = path.join(rootDir, 'lib', 'types.ts');
const typesContent = fs.readFileSync(typesPath, 'utf8');
if (!typesContent.includes('currency?: string | null') || !typesContent.includes('exchange?: string | null')) {
  console.error('❌ lib/types.ts: InstrumentUpdateRequest must contain currency and exchange');
  process.exit(1);
}
if (!typesContent.includes('analysis_reference_price?: number | null') || !typesContent.includes('start_of_year_price?: number | null')) {
  console.error('❌ lib/types.ts: RefreshSingleResponse must contain analysis_reference_price and start_of_year_price');
  process.exit(1);
}
console.log('✅ types.ts contracts verified');

// 2. Verify ManualEntryModal.tsx implementation
const modalPath = path.join(rootDir, 'components', 'ManualEntryModal.tsx');
const modalContent = fs.readFileSync(modalPath, 'utf8');

// Issue 1: Hide "Precio Ref. Análisis" in Creation mode (add form)
// The add form section must not contain an input for addAnalysisPrice or 'Precio Ref. Análisis' label inside the add form
const addFormMatch = modalContent.match(/!isEditMode\s*\?\s*\([\s\S]*?<\s*form[^>]*onSubmit=\{handleAddSubmit\}[\s\S]*?<\/form>/);
if (!addFormMatch) {
  console.error('❌ components/ManualEntryModal.tsx: Could not find handleAddSubmit form');
  process.exit(1);
}
const addFormCode = addFormMatch[0];
if (addFormCode.includes('addAnalysisPrice') || addFormCode.includes('Precio Ref. Análisis')) {
  console.error('❌ components/ManualEntryModal.tsx: Creation mode must NOT render "Precio Ref. Análisis" or addAnalysisPrice');
  process.exit(1);
}
console.log('✅ Creation mode hides "Precio Ref. Análisis" successfully');

// Verify Edit mode retains "Precio Ref. Análisis"
if (!modalContent.includes('editAnalysisPrice') || !modalContent.includes('handleFetchHistoricalForEdit')) {
  console.error('❌ components/ManualEntryModal.tsx: Edit mode must keep editAnalysisPrice and historical lookup');
  process.exit(1);
}
console.log('✅ Edit mode retains "Precio Ref. Análisis" successfully');

// Issue 2: Confirm Ticker Change & Sync Metadata Button in Edit Mode
if (
  !modalContent.includes('Confirmar cambio y actualizar datos') ||
  !modalContent.includes('handleConfirmTickerChange')
) {
  console.error('❌ components/ManualEntryModal.tsx: Missing "Confirmar cambio y actualizar datos" button or handleConfirmTickerChange');
  process.exit(1);
}
console.log('✅ "Confirmar cambio y actualizar datos" button & handler verified');

// Issue 3: editCurrency and editExchange state tracking and flush on ticker change
if (
  !modalContent.includes('editCurrency') ||
  !modalContent.includes('editExchange')
) {
  console.error('❌ components/ManualEntryModal.tsx: Missing editCurrency or editExchange state');
  process.exit(1);
}
console.log('✅ editCurrency and editExchange state tracking verified');

console.log('');
console.log('All Watchlist fixes verification passed! 🚀');
