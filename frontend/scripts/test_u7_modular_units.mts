import assert from 'node:assert/strict';
import {
  getStoredString,
  setStoredString,
  getStoredJson,
  setStoredJson,
  removeStoredItem,
} from '../lib/storage';
import {
  MIN_ROW_HEIGHT,
  DEFAULT_ROW_HEIGHT,
  MAX_ROW_HEIGHT,
  DEFAULT_WATCHLIST_COLUMN_WIDTHS,
  clampRowHeight,
  getRowCellPaddingClass,
  formatPercent,
  formatDeclineToTarget,
  formatStackedDate,
  timeAgo,
  getQuoteTooltip,
  numericSortWithNulls,
  filterWatchlistPositions,
} from '../lib/watchlist-formatters';
import {
  DEFAULT_EXCHANGE,
  DEFAULT_CURRENCY,
  POPULAR_EXCHANGES,
  POPULAR_CURRENCIES,
  normalizeTicker,
  parseOptionalNumber,
  getTodayLocalDateString,
  validateAddInstrumentInput,
  validateEditInstrumentInput,
  buildManualEntryUpdatePayload,
} from '../lib/instrument-constants';
import { translations } from '../lib/translations';
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

function runStorageTests() {
  const originalWindow = (globalThis as { window?: unknown }).window;

  try {
    // 1. SSR safety when window is undefined
    delete (globalThis as { window?: unknown }).window;
    assert.equal(getStoredString('pm_test_key'), null);
    assert.equal(setStoredString('pm_test_key', 'val'), false);
    assert.deepEqual(getStoredJson('pm_test_json', { a: 1 }), { a: 1 });
    assert.equal(setStoredJson('pm_test_json', { a: 2 }), false);
    assert.equal(removeStoredItem('pm_test_key'), false);

    // 2. Normal round-trip and corrupt/invalid JSON fallback
    const map = new Map<string, string>();
    const mockStorage = {
      getItem: (k: string) => map.get(k) ?? null,
      setItem: (k: string, v: string) => {
        map.set(k, v);
      },
      removeItem: (k: string) => {
        map.delete(k);
      },
    };
    (globalThis as { window?: unknown }).window = { localStorage: mockStorage };

    assert.equal(setStoredString('lang', 'es'), true);
    assert.equal(getStoredString('lang'), 'es');
    assert.equal(removeStoredItem('lang'), true);
    assert.equal(getStoredString('lang'), null);

    assert.equal(setStoredJson('cols', { ticker: 120 }), true);
    assert.deepEqual(getStoredJson('cols', {}), { ticker: 120 });

    // Corrupt JSON must return fallback without throwing
    map.set('cols', '{not-valid-json');
    assert.deepEqual(getStoredJson('cols', { ticker: 100 }), { ticker: 100 });

    // Failed type validator must return fallback
    map.set('sorting', JSON.stringify({ wrong: 'shape' }));
    const isArray = (v: unknown): v is Array<{ id: string }> => Array.isArray(v);
    assert.deepEqual(getStoredJson('sorting', [], isArray), []);

    // 3. Fault tolerance for SecurityError / QuotaExceededError
    const throwingStorage = {
      getItem: () => {
        throw new DOMException('Blocked by privacy settings', 'SecurityError');
      },
      setItem: () => {
        throw new DOMException('Storage quota exceeded', 'QuotaExceededError');
      },
      removeItem: () => {
        throw new DOMException('Blocked by privacy settings', 'SecurityError');
      },
    };
    (globalThis as { window?: unknown }).window = { localStorage: throwingStorage };

    assert.equal(getStoredString('any'), null);
    assert.deepEqual(getStoredJson('any', ['fallback']), ['fallback']);
    assert.equal(setStoredString('any', 'x'), false);
    assert.equal(setStoredJson('any', { ok: true }), false);
    assert.equal(removeStoredItem('any'), false);
  } finally {
    if (originalWindow === undefined) {
      delete (globalThis as { window?: unknown }).window;
    } else {
      (globalThis as { window?: unknown }).window = originalWindow;
    }
  }
}

function runWatchlistFormatterTests() {
  assert.equal(MIN_ROW_HEIGHT, 32);
  assert.equal(DEFAULT_ROW_HEIGHT, 48);
  assert.equal(MAX_ROW_HEIGHT, 88);
  assert.equal(clampRowHeight(10), 32);
  assert.equal(clampRowHeight(48.4), 48);
  assert.equal(clampRowHeight(120), 88);
  assert.equal(clampRowHeight(Number.NaN), 48);
  assert.equal(getRowCellPaddingClass(34), 'py-1 px-2');
  assert.equal(getRowCellPaddingClass(48), 'py-1.5 px-2.5');
  assert.equal(getRowCellPaddingClass(64), 'py-2.5 px-3');

  const totalWidth = Object.values(DEFAULT_WATCHLIST_COLUMN_WIDTHS).reduce((acc, w) => acc + w, 0);
  assert.ok(totalWidth <= 1180);

  const posPct = formatPercent(3.456, true);
  assert.equal(posPct.text, '+3.46%');
  assert.ok(posPct.colorClass.includes('text-emerald-400'));

  const negPct = formatPercent(-1.2, true);
  assert.equal(negPct.text, '-1.20%');
  assert.ok(negPct.colorClass.includes('text-rose-400'));

  const invalidPct = formatPercent(Number.NaN, true);
  assert.equal(invalidPct.text, 'N/A');

  const targetReached = formatDeclineToTarget(1.5, true);
  assert.equal(targetReached.text, '+1.50%');
  assert.ok(targetReached.colorClass.includes('bg-emerald-500/20'));

  const imminent = formatDeclineToTarget(-1.5, true);
  assert.ok(imminent.colorClass.includes('animate-pulse'));

  const missingTarget = formatDeclineToTarget(null, false);
  assert.equal(missingTarget.text, '-100.00%');

  const stacked = formatStackedDate('2026-09-07');
  assert.deepEqual(stacked, { dayMonth: '07/09', year: '2026' });
  assert.equal(formatStackedDate(null), null);

  const t = (key: keyof typeof translations.en, params?: Record<string, string | number>) => {
    let txt: string = translations.en[key];
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        txt = txt.replace(`{${k}}`, String(v));
      }
    }
    return txt;
  };

  const now = Date.parse('2026-11-28T10:00:00Z');
  assert.ok(timeAgo('2026-11-28T09:59:40Z', now, t).length > 0);
  assert.equal(timeAgo('not-a-date', now, t), '');

  const tooltip = getQuoteTooltip(makePosition(), t, now);
  assert.ok(tooltip && tooltip.includes('Yahoo'));

  const rowNull = { getValue: () => null };
  const rowNaN = { getValue: () => Number.NaN };
  const rowLow = { getValue: () => 5 };
  const rowHigh = { getValue: () => 20 };
  assert.equal(numericSortWithNulls(rowLow, rowHigh, 'x'), -1);
  assert.equal(numericSortWithNulls(rowNull, rowLow, 'x'), 1);
  assert.equal(numericSortWithNulls(rowLow, rowNaN, 'x'), -1);

  const sample = [
    makePosition({ user_ticker: 'AAPL', company_name: 'Apple Inc.', exchange: 'US', currency: 'USD' }),
    makePosition({ user_ticker: 'SAN.MC', company_name: 'Banco Santander', exchange: 'SPAIN', currency: 'EUR' }),
  ];
  assert.equal(filterWatchlistPositions(sample, { exchange: 'SPAIN', currency: 'ALL', query: '' }).length, 1);
  assert.equal(filterWatchlistPositions(sample, { exchange: 'ALL', currency: 'USD', query: 'apple' }).length, 1);
  assert.equal(filterWatchlistPositions(sample, { exchange: 'ALL', currency: 'ALL', query: 'xyz' }).length, 0);
}

function runInstrumentConstantsTests() {
  assert.equal(DEFAULT_EXCHANGE, 'AUTO');
  assert.equal(DEFAULT_CURRENCY, 'AUTO');
  assert.equal(POPULAR_EXCHANGES[0].value, 'AUTO');
  assert.equal(POPULAR_CURRENCIES[0].value, 'AUTO');

  assert.equal(normalizeTicker('  msft.us  '), 'MSFT.US');
  assert.equal(parseOptionalNumber(' 42.5 '), 42.5);
  assert.equal(parseOptionalNumber('   '), null);
  assert.equal(parseOptionalNumber('abc'), null);
  assert.match(getTodayLocalDateString(), /^\d{4}-\d{2}-\d{2}$/);

  assert.deepEqual(validateAddInstrumentInput({ ticker: '   ', fetchYahoo: true }), {
    valid: false,
    errorKey: 'tickerRequiredError',
  });
  assert.deepEqual(validateAddInstrumentInput({ ticker: 'AAPL', fetchYahoo: true }), { valid: true });

  assert.deepEqual(validateEditInstrumentInput({ ticker: '   ' }), {
    valid: false,
    errorKey: 'tickerEmptyError',
  });
  assert.deepEqual(validateEditInstrumentInput({ ticker: 'MSFT' }), { valid: true });

  const payload = buildManualEntryUpdatePayload({
    originalTicker: 'AAPL',
    editTicker: ' msft ',
    editCompany: '  ',
    editExchange: 'AUTO',
    editCurrency: 'USD',
    editAnalysisDate: '2026-01-10',
    editAnalysisPrice: '180.50',
    editSovDate: '',
    editSovPrice: 'bad-number',
    editTargetPrice: '220',
    editComment: ' thesis ',
    latestPrice: 215,
    todayDate: '2026-11-28',
    updateDateToToday: true,
    isAnalysisPriceManuallyEdited: false,
  });
  assert.equal(payload.new_ticker, 'MSFT');
  assert.equal(payload.company_name, null);
  assert.equal(payload.exchange, null);
  assert.equal(payload.currency, 'USD');
  assert.equal(payload.analysis_date, '2026-11-28');
  assert.equal(payload.analysis_reference_price, 215);
  assert.equal(payload.start_of_year_price, null);
  assert.equal(payload.target_price, 220);
}

runStorageTests();
runWatchlistFormatterTests();
runInstrumentConstantsTests();
console.log('✓ U7 pure utility unit tests (storage, watchlist-formatters, instrument-constants) passed');
