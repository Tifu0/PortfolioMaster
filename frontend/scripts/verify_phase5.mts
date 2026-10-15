import * as api from '../lib/api';
import type { ImportPreviewResponse, ImportConfirmResponse, Instrument } from '../lib/types';
import { ImportView } from '../components/ImportView';

console.log('Testing Phase 5 CSV/Excel Import and API data contracts...');

// 1. Verify API functions are exported
if (typeof api.previewImport !== 'function') {
  console.error('❌ previewImport is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ previewImport is exported from lib/api.ts');

if (typeof api.confirmImport !== 'function') {
  console.error('❌ confirmImport is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ confirmImport is exported from lib/api.ts');

// 2. Verify ImportView component is exported
if (typeof ImportView !== 'function') {
  console.error('❌ ImportView is not exported from components/ImportView.tsx');
  process.exit(1);
}
console.log('✅ ImportView component is exported from components/ImportView.tsx');

// 3. Verify ImportPreviewResponse data contract
const samplePreview: ImportPreviewResponse = {
  instruments: [
    {
      id: null,
      user_ticker: 'AAPL',
      provider_symbol: 'AAPL',
      exchange: 'US',
      currency: 'USD',
      company_name: 'Apple Inc.',
      analysis_date: '2026-01-15',
      analysis_reference_price: 185.0,
      target_price: 220.0,
      comment: 'Core tech',
      active: true,
    },
  ],
  errors: ['Fila 3: Ticker obligatorio'],
  unresolved: ['FOOBAR'],
  warnings: ['Ticker duplicado: AAPL'],
  valid_count: 1,
};

const requiredPreviewKeys: (keyof ImportPreviewResponse)[] = [
  'instruments',
  'errors',
  'unresolved',
  'warnings',
  'valid_count',
];

for (const key of requiredPreviewKeys) {
  if (!(key in samplePreview)) {
    console.error(`❌ ImportPreviewResponse missing property: ${key}`);
    process.exit(1);
  }
}
console.log('✅ ImportPreviewResponse data contract verified');

// 4. Verify ImportConfirmResponse data contract
const sampleConfirm: ImportConfirmResponse = {
  status: 'ok',
  committed: 1,
  errors: [],
};

if (!('status' in sampleConfirm) || !('committed' in sampleConfirm) || !('errors' in sampleConfirm)) {
  console.error('❌ ImportConfirmResponse data contract invalid');
  process.exit(1);
}
console.log('✅ ImportConfirmResponse data contract verified');

console.log('Phase 5 verification complete!');
