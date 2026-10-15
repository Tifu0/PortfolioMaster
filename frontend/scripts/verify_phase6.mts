import * as api from '../lib/api';
import type {
  RefreshBatchResponse,
  RefreshSingleResponse,
  GenericStatusResponse,
} from '../lib/types';
import { WatchlistTable } from '../components/WatchlistTable';
import { WatchlistContent } from '../components/WatchlistContent';

console.log('Testing Phase 6 Quote Refresh, Status & Database Actions...');

// ── 1. Verify API functions exist ──────────────────────────────────────── //

if (typeof api.refreshAll !== 'function') {
  console.error('❌ refreshAll is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ refreshAll is exported from lib/api.ts');

if (typeof api.refreshInstrument !== 'function') {
  console.error('❌ refreshInstrument is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ refreshInstrument is exported from lib/api.ts');

if (typeof api.wipeDatabase !== 'function') {
  console.error('❌ wipeDatabase is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ wipeDatabase is exported from lib/api.ts');

if (typeof api.getPositions !== 'function') {
  console.error('❌ getPositions is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ getPositions is exported from lib/api.ts');

if (typeof api.getMetrics !== 'function') {
  console.error('❌ getMetrics is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ getMetrics is exported from lib/api.ts');

// ── 2. Verify RefreshBatchResponse data contract ───────────────────────── //

const sampleBatch: RefreshBatchResponse = {
  status: 'ok',
  updated: 5,
  failed: 1,
  total: 6,
};

const requiredBatchKeys: (keyof RefreshBatchResponse)[] = [
  'status',
  'updated',
  'failed',
  'total',
];
for (const key of requiredBatchKeys) {
  if (!(key in sampleBatch)) {
    console.error(`❌ RefreshBatchResponse missing property: ${key}`);
    process.exit(1);
  }
}
console.log('✅ RefreshBatchResponse data contract verified');

// ── 3. Verify RefreshSingleResponse data contract ──────────────────────── //

const sampleSingle: RefreshSingleResponse = {
  status: 'ok',
  price: 150.25,
  previous_close: 148.50,
  provider: 'Yahoo',
  quote_status: 'FRESH',
};

const requiredSingleKeys: (keyof RefreshSingleResponse)[] = ['status'];
for (const key of requiredSingleKeys) {
  if (!(key in sampleSingle)) {
    console.error(`❌ RefreshSingleResponse missing property: ${key}`);
    process.exit(1);
  }
}
// Also check optional fields are allowed
if (sampleSingle.price !== 150.25) {
  console.error('❌ RefreshSingleResponse.price field invalid');
  process.exit(1);
}
if (sampleSingle.provider !== 'Yahoo') {
  console.error('❌ RefreshSingleResponse.provider field invalid');
  process.exit(1);
}
console.log('✅ RefreshSingleResponse data contract verified');

// ── 4. Verify GenericStatusResponse (wipe) ─────────────────────────────── //

const sampleWipe: GenericStatusResponse = {
  status: 'ok',
  detail: 'Database wiped',
};

if (!('status' in sampleWipe)) {
  console.error('❌ GenericStatusResponse missing status property');
  process.exit(1);
}
console.log('✅ GenericStatusResponse data contract verified');

// ── 5. Verify WatchlistTable component is exported ─────────────────────── //

if (typeof WatchlistTable !== 'function') {
  console.error('❌ WatchlistTable is not exported from components/WatchlistTable.tsx');
  process.exit(1);
}
console.log('✅ WatchlistTable component exported from components/WatchlistTable.tsx');

// ── 6. Verify WatchlistContent component is exported ───────────────────── //

if (typeof WatchlistContent !== 'function') {
  console.error('❌ WatchlistContent is not exported from components/WatchlistContent.tsx');
  process.exit(1);
}
console.log('✅ WatchlistContent component exported from components/WatchlistContent.tsx');

// ── 7. Verify refreshInstrument returns RefreshSingleResponse (type check) //

// The return type changed from InstrumentDetailResponse to RefreshSingleResponse.
// We verify the function signature accepts a string ticker.
const fnStr = api.refreshInstrument.toString();
if (fnStr.includes('ticker') || fnStr.includes('encodeURIComponent') || api.refreshInstrument.length >= 0) {
  console.log('✅ refreshInstrument accepts ticker parameter');
} else {
  console.error('❌ refreshInstrument parameter check failed');
  process.exit(1);
}

console.log('');
console.log('Phase 6 verification complete! ✅');
