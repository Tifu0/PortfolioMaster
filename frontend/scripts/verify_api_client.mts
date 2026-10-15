import * as api from '../lib/api';

console.log('Testing Phase 2 API Client exports...');

const expectedFunctions = [
  'getPositions',
  'getInstruments',
  'getInstrument',
  'createInstrument',
  'updateInstrument',
  'deleteInstrument',
  'refreshInstrument',
  'refreshAll',
  'previewImport',
  'confirmImport',
  'wipeDatabase',
];

let failed = false;
for (const fnName of expectedFunctions) {
  if (typeof (api as Record<string, unknown>)[fnName] !== 'function') {
    console.error(`❌ Missing expected function: ${fnName}`);
    failed = true;
  } else {
    console.log(`✅ ${fnName} is exported and typed`);
  }
}

if (failed) {
  process.exit(1);
} else {
  console.log('All 11 API client functions verified successfully!');
}
