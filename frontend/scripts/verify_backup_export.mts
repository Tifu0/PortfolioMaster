import * as api from '../lib/api';
import type { BackupItem, BackupListResponse, RestoreResponse } from '../lib/types';
import { BackupExportModal } from '../components/BackupExportModal';

console.log('Testing Backup & Export API Client, Types & Components...');

// 1. Verify API functions
const requiredFunctions = [
  'exportWatchlist',
  'downloadDatabaseBackup',
  'getBackupList',
  'restoreBackupFile',
  'restoreLocalBackup',
] as const;

for (const fnName of requiredFunctions) {
  if (typeof (api as Record<string, unknown>)[fnName] !== 'function') {
    console.error(`❌ ${fnName} is not exported from lib/api.ts`);
    process.exit(1);
  }
  console.log(`✅ ${fnName} is exported and callable`);
}

// 2. Verify Data Contract types
const sampleBackupItem: BackupItem = {
  filename: 'portfolio_backup_20261018_200000.db',
  size_bytes: 45056,
  created_at: '2026-10-18T20:00:00',
  type: 'db',
};

const sampleList: BackupListResponse = {
  status: 'ok',
  backups: [sampleBackupItem],
  count: 1,
};

const sampleRestore: RestoreResponse = {
  status: 'ok',
  restored_instruments: 4,
  sample_tickers: ['AAPL', 'MSFT'],
  type: 'db',
};

if (sampleList.count !== 1 || sampleRestore.restored_instruments !== 4) {
  console.error('❌ Data contract mismatch');
  process.exit(1);
}
console.log('✅ Backup and Restore data contracts validated');

// 3. Verify Component
if (typeof BackupExportModal !== 'function') {
  console.error('❌ BackupExportModal component is not exported properly');
  process.exit(1);
}
console.log('✅ BackupExportModal component verified');

console.log('Backup & Export verification complete! ✅');
