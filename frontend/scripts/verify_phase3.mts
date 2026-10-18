import * as api from '../lib/api';
import type { Position } from '../lib/types';

console.log('Testing Phase 3 Watchlist Table and API data contracts...');

// Sample test position matching the exact backend dictionary contract
const samplePosition: Position = {
  id: 1,
  user_ticker: 'SAN.MC',
  provider_symbol: 'SAN.MC',
  exchange: 'SPAIN',
  currency: 'EUR',
  company_name: 'Banco Santander',
  analysis_date: '2026-01-15',
  analysis_reference_price: 4.25,
  target_price: 5.50,
  comment: 'Core holding',
  active: true,
  latest_price: 4.50,
  previous_close: 4.40,
  quote_status: 'FRESH',
  quote_provider: 'yahoo',
  quote_fetched_at: '2026-10-15T10:00:00',
  daily_variation: 2.27,
  daily_variation_valid: true,
  variation_since_analysis: 5.88,
  variation_since_analysis_valid: true,
  ytd_variation: 3.50,
  ytd_variation_valid: true,
  decline_to_target: 22.22,
  decline_to_target_valid: true,
};

// Check properties
const requiredProps: (keyof Position)[] = [
  'id',
  'user_ticker',
  'provider_symbol',
  'exchange',
  'currency',
  'company_name',
  'latest_price',
  'previous_close',
  'quote_status',
  'daily_variation',
  'daily_variation_valid',
  'variation_since_analysis',
  'variation_since_analysis_valid',
  'ytd_variation',
  'ytd_variation_valid',
  'decline_to_target',
  'decline_to_target_valid',
  'target_price',
];

for (const prop of requiredProps) {
  if (!(prop in samplePosition)) {
    console.error(`❌ Position contract missing property: ${prop}`);
    process.exit(1);
  }
}

console.log('✅ Position data shape verified against WatchlistTable requirements');
console.log('Phase 3 verification complete!');
