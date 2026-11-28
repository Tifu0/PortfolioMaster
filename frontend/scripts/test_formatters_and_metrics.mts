import assert from 'node:assert/strict';
import { formatCurrency } from '../lib/formatters';
import { computePortfolioMetricsFallback } from '../components/MetricCards';
import { buildManualEntryUpdatePayload } from '../components/ManualEntryModal';
import type { Position } from '../lib/types';

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: 1,
    user_ticker: 'AAPL',
    provider_symbol: 'AAPL',
    exchange: 'US',
    currency: 'USD',
    company_name: 'Apple Inc.',
    analysis_date: '2026-01-10',
    analysis_reference_price: 180,
    start_of_year_date: '2026-01-02',
    start_of_year_price: 185,
    target_price: 220,
    comment: '',
    active: true,
    latest_price: 200,
    previous_close: 195,
    quote_status: 'FRESH',
    quote_provider: 'Yahoo',
    quote_fetched_at: '2026-11-28T09:00:00Z',
    daily_variation: 2.56,
    daily_variation_valid: true,
    variation_since_analysis: 11.11,
    variation_since_analysis_valid: true,
    ytd_variation: 8.11,
    ytd_variation_valid: true,
    decline_to_target: -9.09,
    decline_to_target_valid: true,
    ...overrides,
  };
}

function runFormatterTests() {
  const enUsd = formatCurrency(150.5, 'usd', 'en');
  assert.ok(enUsd.includes('150.50') && (enUsd.includes('$') || enUsd.includes('USD')));

  const esUsd = formatCurrency(150.5, 'USD', 'es');
  assert.ok(esUsd.includes('150,50') && (esUsd.includes('$') || esUsd.includes('USD')));

  const eur = formatCurrency(42.25, 'EUR', 'es');
  assert.ok(eur.includes('42,25'));

  const jpy = formatCurrency(1500.89, 'JPY', 'en');
  assert.ok(jpy.includes('1,500.89'));

  const gbx = formatCurrency(520.25, 'GBX', 'en');
  assert.ok(gbx.includes('GBX') && gbx.includes('520.25'));

  const nulCurr = formatCurrency(10, null, 'en');
  assert.ok(nulCurr.includes('10.00'));

  assert.equal(formatCurrency(12345.67, 'usd', 'en'), '$12,345.67');
  assert.equal(formatCurrency(12345.67, 'USD', 'es'), '12.345,67\u00a0US$');
  assert.equal(formatCurrency(12345.67, 'EUR', 'es'), '12.345,67\u00a0€');
  assert.equal(formatCurrency(0, 'JPY', 'en'), '¥0.00');
  assert.equal(formatCurrency(12.5, null, 'es'), '12,50');
  assert.equal(formatCurrency(12.5, 'GBX', 'en'), 'GBX\u00a012.50');

  assert.equal(formatCurrency(null, 'USD', 'en'), '—');
  assert.equal(formatCurrency(undefined, 'USD', 'en'), '—');
  assert.equal(formatCurrency(NaN, 'USD', 'en'), '—');
  assert.equal(formatCurrency(Infinity, 'USD', 'en'), '—');
}

function runMetricsFallbackTests() {
  const empty = computePortfolioMetricsFallback([]);
  assert.equal(empty.total_positions, 0);
  assert.equal(empty.positions_with_quotes, 0);
  assert.equal(empty.best_performer, null);
  assert.equal(empty.average_daily_change, null);

  const computed = computePortfolioMetricsFallback([
    makePosition({ user_ticker: 'GAIN', company_name: 'Gainer', daily_variation: 4.0, daily_variation_valid: true }),
    makePosition({ user_ticker: 'LOSS', company_name: 'Loser', daily_variation: -2.0, daily_variation_valid: true }),
    makePosition({ user_ticker: 'FLAT', company_name: 'Flat', daily_variation: 0.0, daily_variation_valid: true }),
    makePosition({ user_ticker: 'NONE', company_name: 'NoQuote', daily_variation: null, daily_variation_valid: false }),
  ]);

  assert.equal(computed.total_positions, 4);
  assert.equal(computed.positions_with_quotes, 3);
  assert.equal(computed.positive_count, 1);
  assert.equal(computed.negative_count, 1);
  assert.equal(computed.neutral_count, 1);
  assert.equal(computed.best_performer?.user_ticker, 'GAIN');
  assert.equal(computed.worst_performer?.user_ticker, 'LOSS');
  assert.equal(computed.average_daily_change, 0.67);
}

function runManualEntryUpdatePayloadTests() {
  const baseInput = {
    originalTicker: 'AAPL',
    editTicker: 'aapl',
    editCompany: ' Apple Inc. ',
    editExchange: 'US',
    editCurrency: 'USD',
    editAnalysisDate: '2026-01-10',
    editAnalysisPrice: '180.50',
    editSovDate: '2026-01-02',
    editSovPrice: '185.00',
    editTargetPrice: '220.00',
    editComment: ' Core position ',
    editActive: true,
    latestPrice: 215.25,
    todayDate: '2026-11-28',
    updateDateToToday: false,
    isAnalysisPriceManuallyEdited: false,
  };

  // Case 1: standard save preserves editAnalysisDate and editAnalysisPrice
  const regular = buildManualEntryUpdatePayload(baseInput);
  assert.equal(regular.analysis_date, '2026-01-10');
  assert.equal(regular.analysis_reference_price, 180.5);
  assert.equal(regular.company_name, 'Apple Inc.');
  assert.equal(regular.new_ticker, undefined);

  // Case 2: save + update date auto-syncs price when not manually edited
  const synced = buildManualEntryUpdatePayload({
    ...baseInput,
    updateDateToToday: true,
    isAnalysisPriceManuallyEdited: false,
  });
  assert.equal(synced.analysis_date, '2026-11-28');
  assert.equal(synced.analysis_reference_price, 215.25);

  // Case 3: save + update date preserves manual price override
  const manual = buildManualEntryUpdatePayload({
    ...baseInput,
    editAnalysisPrice: '199.99',
    updateDateToToday: true,
    isAnalysisPriceManuallyEdited: true,
  });
  assert.equal(manual.analysis_date, '2026-11-28');
  assert.equal(manual.analysis_reference_price, 199.99);

  // Case 4: ticker rename sets new_ticker uppercase
  const renamed = buildManualEntryUpdatePayload({
    ...baseInput,
    editTicker: ' msft ',
  });
  assert.equal(renamed.new_ticker, 'MSFT');
}

runFormatterTests();
runMetricsFallbackTests();
runManualEntryUpdatePayloadTests();
console.log('✓ Behavioral formatters, metrics fallback, and modal payload tests passed');
