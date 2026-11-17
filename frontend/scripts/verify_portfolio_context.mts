import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

console.log('Testing PortfolioContext exports and interfaces...');

const contextPath = path.join(rootDir, 'context', 'PortfolioContext.tsx');
if (!fs.existsSync(contextPath)) {
  console.error('❌ context/PortfolioContext.tsx does not exist');
  process.exit(1);
}

const content = fs.readFileSync(contextPath, 'utf8');

// Check required exports
const requiredTerms = [
  'PortfolioProvider',
  'usePortfolioData',
  'PortfolioDataContext',
  'refreshPortfolioData',
  'optimisticDelete',
  'optimisticUpdatePosition',
  'positions',
  'metrics',
];

for (const term of requiredTerms) {
  if (!content.includes(term)) {
    console.error(`❌ context/PortfolioContext.tsx missing required export/member: ${term}`);
    process.exit(1);
  }
}

// Check that the watchlist provider receives the verified server snapshot.
const pagePath = path.join(rootDir, 'app', 'page.tsx');
const page = fs.readFileSync(pagePath, 'utf8');
if (!page.includes('<PortfolioProvider') || !page.includes('getServerAuth()') || !page.includes('initialDataReady=')) {
  console.error('❌ app/page.tsx must seed the portfolio provider from authenticated SSR');
  process.exit(1);
}
const refreshContext = fs.readFileSync(path.join(rootDir, 'context', 'PortfolioRefreshContext.tsx'), 'utf8');
if (!refreshContext.includes('PortfolioRefreshContext') || !refreshContext.includes('startRefreshSync')) {
  console.error('❌ Refresh progress needs its own SSE context');
  process.exit(1);
}

// Verify component integrations
const componentsToCheck = [
  { file: 'components/WatchlistContent.tsx', expected: ['usePortfolioData', '<WatchlistRefreshBadge'] },
  { file: 'components/WatchlistTable.tsx', expected: ['usePortfolioDataOptional', 'refreshPortfolioData', 'optimisticUpdatePosition'] },
  { file: 'components/ManualEntryModal.tsx', expected: ['usePortfolioDataOptional', 'optimisticDelete', 'refreshPortfolioData'] },
  { file: 'components/ImportView.tsx', expected: ['usePortfolioDataOptional', 'refreshPortfolioData'] },
  { file: 'components/BackupExportView.tsx', expected: ['usePortfolioDataOptional', 'refreshPortfolioData'] },
  { file: 'components/BackupExportModal.tsx', expected: ['<BackupExportView', 'mode="modal"'] },
];

for (const { file, expected } of componentsToCheck) {
  const filePath = path.join(rootDir, file);
  if (!fs.existsSync(filePath)) {
    console.error(`❌ ${file} does not exist`);
    process.exit(1);
  }
  const fileContent = fs.readFileSync(filePath, 'utf8');
  for (const exp of expected) {
    if (!fileContent.includes(exp)) {
      console.error(`❌ ${file} missing expected integration: ${exp}`);
      process.exit(1);
    }
  }
}

console.log('✅ Authenticated server snapshot and independent portfolio contexts verified');
console.log('✅ All components (WatchlistContent, WatchlistTable, ManualEntryModal, ImportView, BackupExportView, BackupExportModal) verified!');
