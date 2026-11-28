import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createTable, getCoreRowModel, getSortedRowModel } from '@tanstack/table-core';
import { AppRouterContext } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import { AuthProvider } from '../context/AuthContext';
import { LanguageProvider } from '../context/LanguageContext';
import { ToastProvider } from '../components/ui/Toast';
import { WatchlistTable } from '../components/WatchlistTable';
import { buildWatchlistColumns } from '../components/watchlist/watchlistColumns';
import {
  COLUMN_SIZING_STORAGE_KEY,
  DEFAULT_WATCHLIST_COLUMN_WIDTHS,
  compareIsoDates,
  formatStackedDate,
  normalizeIsoDateForSort,
} from '../lib/watchlist-formatters';
import { applyBatchQuotesDelta } from '../context/PortfolioRefreshContext';
import { getStoredJson } from '../lib/storage';
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
    earnings_date: '2027-01-28',
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

function runFormattingAndSsrTests() {
  // 1. Identical formatting utility reused for analysis_date and earnings_date
  assert.deepEqual(formatStackedDate('2027-01-28'), { dayMonth: '28/01', year: '2027' });

  const router = {
    bfcacheId: 'test-earnings-ssr',
    back() {},
    forward() {},
    refresh() {},
    hmrRefresh() {},
    push() {},
    replace() {},
    prefetch() {},
  };

  const positions = [
    makePosition({
      user_ticker: 'AAPL',
      analysis_date: '2027-01-28',
      earnings_date: '2027-01-28',
    }),
    makePosition({
      id: 2,
      user_ticker: 'SPY',
      company_name: 'SPDR S&P 500 ETF',
      analysis_date: null,
      earnings_date: null,
    }),
  ];

  const html = renderToStaticMarkup(
    React.createElement(
      AppRouterContext.Provider,
      { value: router },
      React.createElement(
        LanguageProvider,
        null,
        React.createElement(
          ToastProvider,
          null,
          React.createElement(
            AuthProvider,
            null,
            React.createElement(WatchlistTable, {
              initialPositions: positions,
            })
          )
        )
      )
    )
  );

  // Header rendered with localized copy
  assert.ok(html.includes(translations.en.colEarnings), 'Earnings column header must render');
  // Formatted stacked date matches analysis_date (28/01 + 2027 appears for both analysis_date & earnings_date)
  const dayMonthMatches = html.match(/28\/01/g) ?? [];
  assert.ok(dayMonthMatches.length >= 2, 'earnings_date must use exact same DD/MM stacked format as analysis_date');
  // Missing earnings_date renders exact N/A
  assert.ok(html.includes('>N/A<'), 'Missing earnings_date must render exact N/A');
  // Read-only: earnings_date must NOT expose an inline edit button
  assert.equal(html.includes('earnings_date_edit'), false);
}

function runChronologicalSortTests() {
  assert.equal(normalizeIsoDateForSort('2027-01-28'), '2027-01-28');
  assert.equal(normalizeIsoDateForSort(' 2027-01-28 '), '2027-01-28');
  assert.equal(normalizeIsoDateForSort(null), undefined);
  assert.equal(normalizeIsoDateForSort(undefined), undefined);
  assert.equal(normalizeIsoDateForSort(''), undefined);
  assert.equal(normalizeIsoDateForSort('invalid-date'), undefined);

  assert.ok(compareIsoDates('2026-12-01', '2027-01-15') < 0);
  assert.ok(compareIsoDates('2027-02-01', '2027-01-15') > 0);
  assert.equal(compareIsoDates('2027-01-15', '2027-01-15'), 0);

  const sample = [
    makePosition({ user_ticker: 'NULL_1', earnings_date: null }),
    makePosition({ user_ticker: 'LATER', earnings_date: '2027-03-10' }),
    makePosition({ user_ticker: 'SOONER', earnings_date: '2026-12-18' }),
    makePosition({ user_ticker: 'EMPTY', earnings_date: '' }),
    makePosition({ user_ticker: 'UNDEF', earnings_date: undefined }),
    makePosition({ user_ticker: 'MID', earnings_date: '2027-01-28' }),
  ];

  const realColumns = buildWatchlistColumns({
    editingDateTicker: null,
    updatingDateTickers: new Set(),
    handleStartEditingDate: () => {},
    handleCancelEditingDate: () => {},
    handleSaveDate: () => {},
    refreshingTickers: new Set(),
    batchRefreshing: false,
    handleSingleRefresh: () => {},
    expandedDescriptionTickers: new Set(),
    toggleDescription: () => {},
    language: 'en',
    t: (key) => translations.en[key],
  });

  const sortOrder = (desc: boolean) => {
    const table = createTable({
      data: sample,
      columns: realColumns,
      state: { sorting: [{ id: 'earnings_date', desc }] },
      onStateChange: () => {},
      renderFallbackValue: null,
      getRowId: (row) => row.user_ticker,
      getCoreRowModel: getCoreRowModel(),
      getSortedRowModel: getSortedRowModel(),
    });
    return table.getRowModel().rows.map((r) => r.original.user_ticker);
  };

  const asc = sortOrder(false);
  assert.deepEqual(asc.slice(0, 3), ['SOONER', 'MID', 'LATER']);
  assert.deepEqual(new Set(asc.slice(3)), new Set(['NULL_1', 'EMPTY', 'UNDEF']));

  const desc = sortOrder(true);
  assert.deepEqual(desc.slice(0, 3), ['LATER', 'MID', 'SOONER']);
  assert.deepEqual(new Set(desc.slice(3)), new Set(['NULL_1', 'EMPTY', 'UNDEF']));
}

function runSseDeltaAndStorageCompatibilityTests() {
  // 1. Live SSE batch delta updates earnings_date without page reload
  const initial = [
    makePosition({ user_ticker: 'AAPL', provider_symbol: 'AAPL', earnings_date: null }),
    makePosition({ user_ticker: 'SPY', provider_symbol: 'SPY', earnings_date: '2026-12-01' }),
  ];
  const afterUpdate = applyBatchQuotesDelta(initial, {
    AAPL: { price: 210, previous_close: 205, status: 'FRESH', earnings_date: '2027-01-28' },
    SPY: { price: 590, previous_close: 588, status: 'FRESH', earnings_date: null },
  });
  assert.equal(afterUpdate[0].earnings_date, '2027-01-28');
  assert.equal(afterUpdate[1].earnings_date, null);

  // 2. Column width budget and legacy localStorage compatibility
  assert.ok('earnings_date' in DEFAULT_WATCHLIST_COLUMN_WIDTHS);
  const totalWidth = Object.values(DEFAULT_WATCHLIST_COLUMN_WIDTHS).reduce((acc, w) => acc + w, 0);
  assert.ok(totalWidth <= 1180);

  const originalWindow = (globalThis as { window?: unknown }).window;
  try {
    const legacySizing = { analysis_date: 90, user_ticker: 120 };
    (globalThis as { window?: unknown }).window = {
      localStorage: {
        getItem: (k: string) => (k === COLUMN_SIZING_STORAGE_KEY ? JSON.stringify(legacySizing) : null),
        setItem: () => {},
        removeItem: () => {},
      },
    };
    const loaded = getStoredJson(COLUMN_SIZING_STORAGE_KEY, {});
    assert.deepEqual(loaded, legacySizing);
  } finally {
    if (originalWindow === undefined) {
      delete (globalThis as { window?: unknown }).window;
    } else {
      (globalThis as { window?: unknown }).window = originalWindow;
    }
  }

  // 3. EN/ES i18n keys present
  assert.ok(translations.en.colEarnings && translations.es.colEarnings);
  assert.ok(translations.en.colEarningsDate && translations.es.colEarningsDate);
  assert.ok(translations.en.sortByEarningsDate && translations.es.sortByEarningsDate);
}

runFormattingAndSsrTests();
runChronologicalSortTests();
runSseDeltaAndStorageCompatibilityTests();
console.log('✓ Behavioral earnings_date column, sorting, SSE delta, and compatibility tests passed');
