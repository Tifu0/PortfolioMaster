import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AppRouterContext } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import { AuthProvider } from '../context/AuthContext';
import { LanguageProvider } from '../context/LanguageContext';
import { ToastProvider } from '../components/ui/Toast';
import {
  DEFAULT_WATCHLIST_COLUMN_WIDTHS,
  WatchlistTable,
  clampRowHeight,
  formatStackedDate,
} from '../components/WatchlistTable';
import type { Position } from '../lib/types';

function makePosition(index: number): Position {
  return {
    id: index,
    user_ticker: `TICK_${String(index).padStart(3, '0')}`,
    provider_symbol: `TICK_${index}`,
    exchange: 'US',
    currency: 'USD',
    company_name: `Company ${index}`,
    analysis_date: '2026-01-10',
    analysis_reference_price: 100,
    start_of_year_date: '2026-01-02',
    start_of_year_price: 95,
    target_price: 120,
    comment: 'Note',
    active: true,
    latest_price: 110,
    previous_close: 105,
    quote_status: 'FRESH',
    quote_provider: 'Yahoo',
    quote_fetched_at: '2026-11-28T09:00:00Z',
    daily_variation: 4.76,
    daily_variation_valid: true,
    variation_since_analysis: 10.0,
    variation_since_analysis_valid: true,
    ytd_variation: 15.79,
    ytd_variation_valid: true,
    decline_to_target: -8.33,
    decline_to_target_valid: true,
  };
}

function runColumnWidthBudgetTests() {
  const totalWidth = Object.values(DEFAULT_WATCHLIST_COLUMN_WIDTHS).reduce((acc, w) => acc + w, 0);
  assert.ok(
    totalWidth <= 1180,
    `Default WatchlistTable column widths (${totalWidth}px) must fit within 1180px for 1280x800 desktop viewports`
  );
  assert.ok(DEFAULT_WATCHLIST_COLUMN_WIDTHS.decline_to_target >= 95);
  assert.ok(DEFAULT_WATCHLIST_COLUMN_WIDTHS.target_price >= 85);
  assert.ok(DEFAULT_WATCHLIST_COLUMN_WIDTHS.actions >= 55);
}

function runRowHeightAndDateHelperTests() {
  assert.equal(clampRowHeight(10), 32);
  assert.equal(clampRowHeight(32), 32);
  assert.equal(clampRowHeight(48), 48);
  assert.equal(clampRowHeight(150), 88);
  assert.equal(clampRowHeight(Number.NaN), 48);

  const valid = formatStackedDate('2026-09-17');
  assert.ok(valid !== null && valid.dayMonth === '17/09' && valid.year === '2026');
  assert.equal(formatStackedDate(null), null);
  assert.equal(formatStackedDate('invalid'), null);
}

function runSsrVirtualizationTests() {
  const manyPositions = Array.from({ length: 300 }, (_, i) => makePosition(i));
  const router = {
    bfcacheId: 'test-table-ssr',
    back() {},
    forward() {},
    refresh() {},
    hmrRefresh() {},
    push() {},
    replace() {},
    prefetch() {},
  };
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
              initialPositions: manyPositions,
              onDataChange: () => {},
              onAddInstrument: () => {},
              onEditTicker: () => {},
            })
          )
        )
      )
    )
  );

  const renderedTickers = new Set(html.match(/TICK_\d{3}/g));
  assert.ok(renderedTickers.has('TICK_000'), 'Initial SSR table must render the first rows');
  assert.ok(renderedTickers.size < 50, `SSR rendered ${renderedTickers.size} rows instead of a bounded viewport slice`);
  assert.equal(html.includes('TICK_299'), false, 'Virtualization must avoid rendering row 299 in initial DOM');
}

runColumnWidthBudgetTests();
runRowHeightAndDateHelperTests();
runSsrVirtualizationTests();
console.log('✓ WatchlistTable SSR virtualization, width budget, and helper tests passed');
