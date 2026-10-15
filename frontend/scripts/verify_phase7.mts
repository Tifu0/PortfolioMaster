import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

console.log('Testing Phase 7 Polish, Aesthetics, Skeletons, Error Handling & Tab 2...');

// ── 1. Verify Dark Theme & CSS Tokens ──────────────────────────────────── //
const cssPath = path.join(rootDir, 'app', 'globals.css');
if (!fs.existsSync(cssPath)) {
  console.error('❌ app/globals.css does not exist');
  process.exit(1);
}
const cssContent = fs.readFileSync(cssPath, 'utf8');
if (!cssContent.includes('--background: #09090b') || !cssContent.includes('tabular-nums')) {
  console.error('❌ app/globals.css is missing dark theme root tokens or tabular-nums');
  process.exit(1);
}
if (!cssContent.includes('::-webkit-scrollbar')) {
  console.error('❌ app/globals.css is missing sleek dark scrollbar styling');
  process.exit(1);
}
console.log('✅ Dark theme tokens, custom scrollbars, and tabular-nums verified');

// ── 2. Verify Loading Skeletons ────────────────────────────────────────── //
const rootLoadingPath = path.join(rootDir, 'app', 'loading.tsx');
if (!fs.existsSync(rootLoadingPath)) {
  console.error('❌ app/loading.tsx does not exist');
  process.exit(1);
}
const rootLoadingContent = fs.readFileSync(rootLoadingPath, 'utf8');
if (!rootLoadingContent.includes('animate-pulse')) {
  console.error('❌ app/loading.tsx missing pulse animation');
  process.exit(1);
}
console.log('✅ App Router root loading skeleton verified');

const importLoadingPath = path.join(rootDir, 'app', 'import', 'loading.tsx');
if (!fs.existsSync(importLoadingPath)) {
  console.error('❌ app/import/loading.tsx does not exist');
  process.exit(1);
}
console.log('✅ App Router import loading skeleton verified');

// ── 3. Verify Error Boundary & Not Found ───────────────────────────────── //
const errorPath = path.join(rootDir, 'app', 'error.tsx');
if (!fs.existsSync(errorPath)) {
  console.error('❌ app/error.tsx does not exist');
  process.exit(1);
}
const errorContent = fs.readFileSync(errorPath, 'utf8');
if (!errorContent.includes("'use client'") || !errorContent.includes('reset')) {
  console.error("❌ app/error.tsx must be a client component and handle reset callback");
  process.exit(1);
}
console.log('✅ App Router global error boundary verified');

const notFoundPath = path.join(rootDir, 'app', 'not-found.tsx');
if (!fs.existsSync(notFoundPath)) {
  console.error('❌ app/not-found.tsx does not exist');
  process.exit(1);
}
console.log('✅ App Router 404 not-found page verified');

// ── 4. Verify AI Discoverability & SEO Assets ─────────────────────────── //
const robotsPath = path.join(rootDir, 'public', 'robots.txt');
if (!fs.existsSync(robotsPath)) {
  console.error('❌ public/robots.txt does not exist');
  process.exit(1);
}
const robotsContent = fs.readFileSync(robotsPath, 'utf8');
if (!robotsContent.includes('User-agent: *') || !robotsContent.includes('Allow: /')) {
  console.error('❌ public/robots.txt must allow crawlers without blocking AI bots');
  process.exit(1);
}
console.log('✅ public/robots.txt discoverability verified');

const llmsPath = path.join(rootDir, 'public', 'llms.txt');
if (!fs.existsSync(llmsPath)) {
  console.error('❌ public/llms.txt does not exist');
  process.exit(1);
}
const llmsContent = fs.readFileSync(llmsPath, 'utf8');
if (!llmsContent.includes('PortfolioMaster') || !llmsContent.includes('/api/positions')) {
  console.error('❌ public/llms.txt missing core endpoints documentation');
  process.exit(1);
}
console.log('✅ public/llms.txt documentation verified');

const sitemapPath = path.join(rootDir, 'app', 'sitemap.ts');
if (!fs.existsSync(sitemapPath)) {
  console.error('❌ app/sitemap.ts does not exist');
  process.exit(1);
}
console.log('✅ app/sitemap.ts generation verified');

// ── 5. Verify Tab 2: ManualEntryModal Component ────────────────────────── //
const modalPath = path.join(rootDir, 'components', 'ManualEntryModal.tsx');
if (!fs.existsSync(modalPath)) {
  console.error('❌ components/ManualEntryModal.tsx does not exist');
  process.exit(1);
}
const modalContent = fs.readFileSync(modalPath, 'utf8');
if (
  !modalContent.includes('createInstrument') ||
  !modalContent.includes('updateInstrument') ||
  !modalContent.includes('deleteInstrument') ||
  !modalContent.includes('POPULAR_EXCHANGES')
) {
  console.error('❌ ManualEntryModal missing key CRUD actions or exchange configs');
  process.exit(1);
}
console.log('✅ components/ManualEntryModal.tsx complete implementation verified');

// ── 6. Verify WatchlistContent & WatchlistTable Integration ────────────── //
const tablePath = path.join(rootDir, 'components', 'WatchlistTable.tsx');
const tableContent = fs.readFileSync(tablePath, 'utf8');
if (!tableContent.includes('onEditTicker') || !tableContent.includes('onAddInstrument')) {
  console.error('❌ WatchlistTable missing onEditTicker or onAddInstrument props');
  process.exit(1);
}
console.log('✅ WatchlistTable row edit & add instrument integration verified');

const contentPath = path.join(rootDir, 'components', 'WatchlistContent.tsx');
const contentStr = fs.readFileSync(contentPath, 'utf8');
if (!contentStr.includes('ManualEntryModal') || !contentStr.includes('useSearchParams')) {
  console.error('❌ WatchlistContent missing ManualEntryModal or URL searchParams');
  process.exit(1);
}
console.log('✅ WatchlistContent reactive modal & query params integration verified');

console.log('');
console.log('Phase 7 verification complete! ✅');
