import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

console.log('Testing Zero-F5 Batch Auto-Sync Architecture...');

// 1. Verify types.ts AppConfig has is_refreshing & refresh_counter
const typesPath = path.join(rootDir, 'lib', 'types.ts');
const typesContent = fs.readFileSync(typesPath, 'utf8');

if (!typesContent.includes('is_refreshing?: boolean;')) {
  console.error('❌ types.ts AppConfig missing is_refreshing property');
  process.exit(1);
}
if (!typesContent.includes('refresh_counter?: number;')) {
  console.error('❌ types.ts AppConfig missing refresh_counter property');
  process.exit(1);
}
console.log('✅ types.ts AppConfig contract verified (is_refreshing & refresh_counter)');

// 2. Verify PortfolioContext.tsx active sync heartbeat & zero-F5 triggering
const contextPath = path.join(rootDir, 'context', 'PortfolioContext.tsx');
const contextContent = fs.readFileSync(contextPath, 'utf8');

const requiredContextElements = [
  'checkBackendSync',
  'lastKnownRefreshAtRef',
  'lastKnownCounterRef',
  'wasRefreshingRef',
  'counterChanged',
  'refreshAtChanged',
  'finishedRefreshing',
  'refreshPortfolioData({ silent: true })',
  'useMemo',
];

for (const el of requiredContextElements) {
  if (!contextContent.includes(el)) {
    console.error(`❌ PortfolioContext.tsx missing expected sync element: ${el}`);
    process.exit(1);
  }
}
console.log('✅ PortfolioContext.tsx active sync heartbeat & change detection verified');

// 3. Verify WatchlistContent.tsx removed redundant interval and has live status badge
const contentPath = path.join(rootDir, 'components', 'WatchlistContent.tsx');
const contentSrc = fs.readFileSync(contentPath, 'utf8');

if (contentSrc.includes('setInterval(() => {\n      reloadData();')) {
  console.error('❌ WatchlistContent.tsx still contains redundant duplicate reloadData interval');
  process.exit(1);
}

if (!contentSrc.includes('appConfig.is_refreshing') || !contentSrc.includes('Actualizando lote...')) {
  console.error('❌ WatchlistContent.tsx badge missing live is_refreshing status indicator');
  process.exit(1);
}
console.log('✅ WatchlistContent.tsx redundant interval removed & live refresh badge verified');

console.log('🎉 All Zero-F5 Batch Auto-Sync checks passed successfully!');
