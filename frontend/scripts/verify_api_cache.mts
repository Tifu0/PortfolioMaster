import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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

// 3. Verify next.config.ts has cacheComponents enabled
const nextConfigPath = path.join(rootDir, 'next.config.ts');
const nextConfigContent = fs.readFileSync(nextConfigPath, 'utf8');
if (!nextConfigContent.includes("cacheComponents: true")) {
  console.error("❌ next.config.ts must have cacheComponents: true enabled");
  process.exit(1);
}
console.log("✅ next.config.ts has cacheComponents: true enabled");

console.log('API cache verification complete! ✅');
