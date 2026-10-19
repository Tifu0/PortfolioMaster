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
  'usePortfolio',
  'refreshPortfolioData',
  'optimisticDelete',
  'optimisticUpdatePosition',
  'positions',
  'metrics',
  'config',
  'isRefreshing',
];

for (const term of requiredTerms) {
  if (!content.includes(term)) {
    console.error(`❌ context/PortfolioContext.tsx missing required export/member: ${term}`);
    process.exit(1);
  }
}

// Check layout integration
const layoutPath = path.join(rootDir, 'app', 'layout.tsx');
const layoutContent = fs.readFileSync(layoutPath, 'utf8');
if (!layoutContent.includes('PortfolioProvider')) {
  console.error('❌ app/layout.tsx must wrap children in PortfolioProvider');
  process.exit(1);
}

// Verify component integrations
const componentsToCheck = [
  { file: 'components/WatchlistContent.tsx', expected: ['usePortfolio', 'seedInitialData', 'refreshPortfolioData'] },
  { file: 'components/WatchlistTable.tsx', expected: ['usePortfolio', 'refreshPortfolioData', 'optimisticUpdatePosition'] },
  { file: 'components/ManualEntryModal.tsx', expected: ['usePortfolio', 'optimisticDelete', 'refreshPortfolioData'] },
  { file: 'components/ImportView.tsx', expected: ['usePortfolio', 'refreshPortfolioData'] },
  { file: 'components/BackupExportView.tsx', expected: ['usePortfolio', 'refreshPortfolioData'] },
  { file: 'components/BackupExportModal.tsx', expected: ['usePortfolio', 'refreshPortfolioData'] },
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

console.log('✅ PortfolioContext and layout integration verified successfully!');
console.log('✅ All components (WatchlistContent, WatchlistTable, ManualEntryModal, ImportView, BackupExportView, BackupExportModal) verified!');
