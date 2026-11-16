import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import nextConfig from '../next.config';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

console.log('Testing API Client and App Router caching configuration...');

const apiPath = path.join(rootDir, 'lib', 'api.ts');
const apiContent = fs.readFileSync(apiPath, 'utf8');

// 1. Verify getConfig has cache: 'no-store'
if (!apiContent.includes("getConfig(): Promise<AppConfig>") || !apiContent.includes("fetch(`${API_BASE_URL}/api/config`, {\n    cache: 'no-store'")) {
  console.error("❌ getConfig must explicitly specify cache: 'no-store'");
  process.exit(1);
}
console.log("✅ getConfig explicitly uses cache: 'no-store'");

// 2. Verify checkYahooTicker has cache: 'no-store'
if (!apiContent.includes("checkYahooTicker(ticker: string") || !apiContent.includes("cache: 'no-store'")) {
  console.error("❌ checkYahooTicker must explicitly specify cache: 'no-store'");
  process.exit(1);
}
console.log("✅ checkYahooTicker explicitly uses cache: 'no-store'");

// 3. Verify the application uses the default Next.js caching configuration.
assert.equal(Object.hasOwn(nextConfig, 'cacheComponents'), false, 'cacheComponents must be omitted');
assert.equal(Object.hasOwn(nextConfig, 'partialPrefetching'), false, 'partialPrefetching must be omitted');
console.log('✅ Next.js caching opt-ins are omitted');

console.log('API cache verification complete! ✅');
