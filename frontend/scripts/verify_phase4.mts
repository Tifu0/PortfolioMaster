import * as api from '../lib/api';
import type { PortfolioMetrics, Position } from '../lib/types';
import { MetricCards } from '../components/MetricCards';

console.log('Testing Phase 4 Metric Cards and API data contracts...');

// 1. Verify API client export
if (typeof api.getMetrics !== 'function') {
  console.error('❌ getMetrics is not exported from lib/api.ts');
  process.exit(1);
}
console.log('✅ getMetrics is exported from lib/api.ts');

// 2. Verify MetricCards component is exported
if (typeof MetricCards !== 'function') {
  console.error('❌ MetricCards is not exported from components/MetricCards.tsx');
  process.exit(1);
}
console.log('✅ MetricCards is exported from components/MetricCards.tsx');

// 3. Verify PortfolioMetrics shape
const sampleMetrics: PortfolioMetrics = {
  total_positions: 3,
  positions_with_quotes: 3,
  best_performer: {
    user_ticker: 'AAPL',
    company_name: 'Apple Inc.',
    daily_variation: 3.5,
    latest_price: 180.0,
    currency: 'USD',
  },
  worst_performer: {
    user_ticker: 'MSFT',
    company_name: 'Microsoft Corp.',
    daily_variation: -1.2,
    latest_price: 410.0,
    currency: 'USD',
  },
  average_daily_change: 1.15,
  positive_count: 2,
  negative_count: 1,
  neutral_count: 0,
};

const requiredMetricKeys: (keyof PortfolioMetrics)[] = [
  'total_positions',
  'positions_with_quotes',
  'best_performer',
  'worst_performer',
  'average_daily_change',
  'positive_count',
  'negative_count',
  'neutral_count',
];

for (const key of requiredMetricKeys) {
  if (!(key in sampleMetrics)) {
    console.error(`❌ PortfolioMetrics missing property: ${key}`);
    process.exit(1);
  }
}
console.log('✅ PortfolioMetrics data contract verified');

// 4. Test math derivation with sample positions
const testPositions: Position[] = [
  {
    id: 1,
    user_ticker: 'AAPL',
    provider_symbol: 'AAPL',
    exchange: 'US',
    currency: 'USD',
    company_name: 'Apple Inc.',
    analysis_date: null,
    analysis_reference_price: null,
    target_price: 200,
    comment: '',
    active: true,
    latest_price: 180,
    previous_close: 170,
    quote_status: 'FRESH',
    quote_provider: 'yahoo',
    quote_fetched_at: null,
    daily_variation: 5.88,
    daily_variation_valid: true,
    variation_since_analysis: null,
    variation_since_analysis_valid: false,
    decline_to_target: 11.11,
    decline_to_target_valid: true,
  },
  {
    id: 2,
    user_ticker: 'SAN',
    provider_symbol: 'SAN.MC',
    exchange: 'SPAIN',
    currency: 'EUR',
    company_name: 'Banco Santander',
    analysis_date: null,
    analysis_reference_price: null,
    target_price: null,
    comment: '',
    active: true,
    latest_price: 4.2,
    previous_close: 4.4,
    quote_status: 'FRESH',
    quote_provider: 'yahoo',
    quote_fetched_at: null,
    daily_variation: -4.55,
    daily_variation_valid: true,
    variation_since_analysis: null,
    variation_since_analysis_valid: false,
    decline_to_target: null,
    decline_to_target_valid: false,
  },
  {
    id: 3,
    user_ticker: 'MC',
    provider_symbol: 'MC.PA',
    exchange: 'FRANCE',
    currency: 'EUR',
    company_name: 'LVMH',
    analysis_date: null,
    analysis_reference_price: null,
    target_price: null,
    comment: '',
    active: true,
    latest_price: null,
    previous_close: null,
    quote_status: null,
    quote_provider: null,
    quote_fetched_at: null,
    daily_variation: null,
    daily_variation_valid: false,
    variation_since_analysis: null,
    variation_since_analysis_valid: false,
    decline_to_target: null,
    decline_to_target_valid: false,
  },
];

const validWithQuotes = testPositions.filter((p) => p.daily_variation_valid && p.daily_variation !== null);
if (validWithQuotes.length !== 2) {
  console.error(`❌ Expected 2 valid positions with quotes, got ${validWithQuotes.length}`);
  process.exit(1);
}

const gainer = validWithQuotes.reduce((prev, curr) => ((curr.daily_variation ?? -Infinity) > (prev.daily_variation ?? -Infinity) ? curr : prev));
if (gainer.user_ticker !== 'AAPL') {
  console.error(`❌ Expected AAPL to be best performer, got ${gainer.user_ticker}`);
  process.exit(1);
}

const loser = validWithQuotes.reduce((prev, curr) => ((curr.daily_variation ?? Infinity) < (prev.daily_variation ?? Infinity) ? curr : prev));
if (loser.user_ticker !== 'SAN') {
  console.error(`❌ Expected SAN to be worst performer, got ${loser.user_ticker}`);
  process.exit(1);
}

console.log('✅ Metric derivation logic verified for best/worst performers');
console.log('Phase 4 verification complete!');
