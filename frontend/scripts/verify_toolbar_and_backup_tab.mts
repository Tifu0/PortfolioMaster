import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { BackupExportView } from '../components/BackupExportView';
import {
  DEFAULT_TOOLBAR_CONFIG,
  TOOLBAR_STORAGE_KEY,
  type ToolbarConfig,
} from '../components/WatchlistTable';

console.log('Testing Dedicated Backup & Export Tab and Customizable Toolbar...');

// 1. Verify BackupExportView component
if (typeof BackupExportView !== 'function') {
  console.error('❌ BackupExportView is not a valid component');
  process.exit(1);
}
console.log('✅ BackupExportView component exported and valid');

// 2. Verify Toolbar Config Defaults
const expectedDefaults: ToolbarConfig = {
  updateQuotes: true,
  addInstrument: true,
  restoreColumns: true,
  rowHeight: false,
  exportBackup: true,
  importValues: false,
  wipeDatabase: false,
};

for (const [key, expectedValue] of Object.entries(expectedDefaults)) {
  const actualValue = DEFAULT_TOOLBAR_CONFIG[key as keyof ToolbarConfig];
  if (actualValue !== expectedValue) {
    console.error(`❌ DEFAULT_TOOLBAR_CONFIG.${key} is ${actualValue}, expected ${expectedValue}`);
    process.exit(1);
  }
}
console.log('✅ DEFAULT_TOOLBAR_CONFIG defaults match exact requirements');

// 3. Verify LocalStorage key
if (TOOLBAR_STORAGE_KEY !== 'portfoliomaster_toolbar_config') {
  console.error(`❌ TOOLBAR_STORAGE_KEY is "${TOOLBAR_STORAGE_KEY}", expected "portfoliomaster_toolbar_config"`);
  process.exit(1);
}
console.log('✅ TOOLBAR_STORAGE_KEY matches "portfoliomaster_toolbar_config"');

// 4. Verify HeaderNav has Backup & Export tab
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const headerNavPath = path.resolve(__dirname, '../components/HeaderNav.tsx');
const headerNavContent = fs.readFileSync(headerNavPath, 'utf-8');

if (!headerNavContent.includes('/backup') || !headerNavContent.includes('Backup & Export')) {
  console.error('❌ HeaderNav does not include /backup or "Backup & Export" tab');
  process.exit(1);
}
console.log('✅ HeaderNav contains Backup & Export navigation tab with /backup route');

// 5. Verify Backup page and loading skeleton exist
const backupPagePath = path.resolve(__dirname, '../app/backup/page.tsx');
const backupLoadingPath = path.resolve(__dirname, '../app/backup/loading.tsx');

if (!fs.existsSync(backupPagePath)) {
  console.error('❌ app/backup/page.tsx does not exist');
  process.exit(1);
}
if (!fs.existsSync(backupLoadingPath)) {
  console.error('❌ app/backup/loading.tsx does not exist');
  process.exit(1);
}
console.log('✅ app/backup/page.tsx and app/backup/loading.tsx exist');

// 6. Verify WatchlistTable features Settings popover and Quick Import button
const watchlistTablePath = path.resolve(__dirname, '../components/WatchlistTable.tsx');
const watchlistTableContent = fs.readFileSync(watchlistTablePath, 'utf-8');

if (!watchlistTableContent.includes('SlidersHorizontal') || !watchlistTableContent.includes('settingsOpen')) {
  console.error('❌ WatchlistTable does not include Settings popover with SlidersHorizontal');
  process.exit(1);
}
if (!watchlistTableContent.includes('/import') || !watchlistTableContent.includes('toolbarConfig.importValues')) {
  console.error('❌ WatchlistTable does not include Quick Import button wired to toolbarConfig.importValues');
  process.exit(1);
}
if (!watchlistTableContent.includes('handleResetToolbarConfig')) {
  console.error('❌ WatchlistTable does not include Reset to Defaults option');
  process.exit(1);
}
console.log('✅ WatchlistTable has Quick Import, Settings Popover, and Reset to Defaults');

console.log('All Toolbar and Backup Tab tests passed successfully! 🚀');
