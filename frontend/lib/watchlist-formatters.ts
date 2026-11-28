import type { TranslationKey } from './translations';
import type { Position } from './types';

/**
 * Empirical row height bounds:
 * - MIN_ROW_HEIGHT (32px): keeps stacked dates, badges, and 26px action buttons legible.
 * - DEFAULT_ROW_HEIGHT (48px): balanced standard table density.
 * - MAX_ROW_HEIGHT (88px): spacious comfortable density for large displays.
 */
export const MIN_ROW_HEIGHT = 32;
export const DEFAULT_ROW_HEIGHT = 48;
export const MAX_ROW_HEIGHT = 88;
export const ROW_HEIGHT_STORAGE_KEY = 'portfoliomaster_row_height';
export const SORTING_STORAGE_KEY = 'portfoliomaster_table_sorting';
export const COLUMN_SIZING_STORAGE_KEY = 'portfoliomaster_column_sizing';

export const DEFAULT_WATCHLIST_COLUMN_WIDTHS = {
  analysis_date: 80,
  user_ticker: 105,
  company_name: 150,
  exchange: 82,
  currency: 66,
  latest_price: 104,
  daily_variation: 94,
  ytd_variation: 98,
  variation_since_analysis: 106,
  decline_to_target: 104,
  target_price: 95,
  actions: 84,
} as const;

export type TranslateFn = (key: TranslationKey, params?: Record<string, string | number>) => string;

export function clampRowHeight(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_ROW_HEIGHT;
  }
  return Math.max(MIN_ROW_HEIGHT, Math.min(MAX_ROW_HEIGHT, Math.round(value)));
}

export function getRowCellPaddingClass(rowHeight: number): string {
  if (rowHeight <= 36) return 'py-1 px-2';
  if (rowHeight >= 60) return 'py-2.5 px-3';
  return 'py-1.5 px-2.5';
}

export function formatPercent(
  value: number | null | undefined,
  valid: boolean
): { text: string; colorClass: string } {
  if (!valid || value === null || value === undefined || isNaN(value)) {
    return { text: 'N/A', colorClass: 'text-zinc-500 font-mono text-xs' };
  }
  const formatted = `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  if (value > 0.0001) {
    return { text: formatted, colorClass: 'text-emerald-400 font-semibold font-mono' };
  }
  if (value < -0.0001) {
    return { text: formatted, colorClass: 'text-rose-400 font-semibold font-mono' };
  }
  return { text: formatted, colorClass: 'text-zinc-300 font-mono' };
}

export function formatDeclineToTarget(
  value: number | null | undefined,
  valid: boolean
): { text: string; colorClass: string } {
  // Missing target prices default to -100% (lowest red intensity) so sorting stays consistent.
  const effectiveValue =
    !valid || value === null || value === undefined || isNaN(value) ? -100 : value;

  const formatted = `${effectiveValue >= 0 ? '+' : ''}${effectiveValue.toFixed(2)}%`;

  if (effectiveValue >= 0) {
    return {
      text: formatted,
      colorClass:
        'text-emerald-300 font-bold font-mono text-xs px-2 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-500/40 shadow-sm shadow-emerald-950/40',
    };
  }

  const absVal = Math.abs(effectiveValue);

  if (absVal <= 2) {
    return {
      text: formatted,
      colorClass:
        'text-rose-100 font-bold font-mono text-xs px-2 py-0.5 rounded-md bg-rose-600/40 border border-rose-500/60 shadow-md shadow-rose-950/60 animate-pulse',
    };
  }
  if (absVal <= 5) {
    return {
      text: formatted,
      colorClass:
        'text-rose-200 font-bold font-mono text-xs px-1.5 py-0.5 rounded bg-rose-500/25 border border-rose-500/40',
    };
  }
  if (absVal <= 10) {
    return {
      text: formatted,
      colorClass:
        'text-rose-300 font-semibold font-mono text-xs px-1.5 py-0.5 rounded bg-rose-500/15 border border-rose-500/25',
    };
  }
  if (absVal <= 30) {
    return { text: formatted, colorClass: 'text-rose-400 font-medium font-mono text-xs' };
  }
  if (absVal <= 50) {
    return { text: formatted, colorClass: 'text-rose-400/80 font-normal font-mono text-xs' };
  }
  if (absVal <= 75) {
    return { text: formatted, colorClass: 'text-rose-400/50 font-normal font-mono text-xs' };
  }
  return { text: formatted, colorClass: 'text-rose-400/30 font-normal font-mono text-xs' };
}

export function timeAgo(isoDate: string | null | undefined, now: number, t: TranslateFn): string {
  if (!isoDate) return '';
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return '';
    const seconds = Math.floor((now - d.getTime()) / 1000);
    if (seconds < 60) return t('timeAgoSeconds');
    if (seconds < 3600) return t('timeAgoMinutes', { n: Math.floor(seconds / 60) });
    if (seconds < 86400) return t('timeAgoHours', { n: Math.floor(seconds / 3600) });
    return t('timeAgoDays', { n: Math.floor(seconds / 86400) });
  } catch {
    return '';
  }
}

export function formatStackedDate(
  isoDate: string | null | undefined
): { dayMonth: string; year: string } | null {
  if (!isoDate || typeof isoDate !== 'string') return null;
  const parts = isoDate.split('-');
  if (parts.length >= 3 && parts[0] && parts[1] && parts[2]) {
    const year = parts[0].trim();
    const month = parts[1].trim();
    const day = parts[2].trim().slice(0, 2);
    if (day && month && year) {
      return { dayMonth: `${day}/${month}`, year };
    }
  }
  return null;
}

export function getQuoteTooltip(pos: Position, t: TranslateFn, now?: number): string | undefined {
  const s = pos.quote_status ? String(pos.quote_status).toUpperCase() : null;
  const statusMap: Record<string, string> = {
    FRESH: t('quoteStatusFresh'),
    DELAYED: t('quoteStatusDelayed'),
    STALE: t('quoteStatusStale'),
    UNAVAILABLE: t('quoteStatusUnavailable'),
    ERROR: t('quoteStatusError'),
  };

  const parts: string[] = [];
  if (s && statusMap[s]) {
    parts.push(statusMap[s]);
  } else if (s) {
    parts.push(s);
  }
  if (pos.quote_provider) {
    parts.push(t('quoteProviderLabel', { provider: pos.quote_provider }));
  }
  const elapsed = now === undefined ? '' : timeAgo(pos.quote_fetched_at, now, t);
  if (elapsed) {
    parts.push(elapsed);
  }
  return parts.length > 0 ? parts.join(' · ') : undefined;
}

export function numericSortWithNulls(
  rowA: { getValue: (id: string) => unknown },
  rowB: { getValue: (id: string) => unknown },
  columnId: string
): number {
  const valA = rowA.getValue(columnId);
  const valB = rowB.getValue(columnId);
  if (valA == null && valB == null) return 0;
  if (valA == null) return 1;
  if (valB == null) return -1;
  const numA = typeof valA === 'number' ? valA : Number(valA);
  const numB = typeof valB === 'number' ? valB : Number(valB);
  const isNaNA = Number.isNaN(numA);
  const isNaNB = Number.isNaN(numB);
  if (isNaNA && isNaNB) return 0;
  if (isNaNA) return 1;
  if (isNaNB) return -1;
  return numA > numB ? 1 : numA < numB ? -1 : 0;
}

export function filterWatchlistPositions(
  positions: Position[],
  filters: { exchange: string; currency: string; query: string }
): Position[] {
  const q = filters.query.trim().toLowerCase();
  return positions.filter((item) => {
    if (filters.exchange !== 'ALL' && item.exchange !== filters.exchange) return false;
    if (filters.currency !== 'ALL' && item.currency !== filters.currency) return false;
    if (q) {
      const matchTicker = item.user_ticker.toLowerCase().includes(q);
      const matchCompany = (item.company_name || '').toLowerCase().includes(q);
      if (!matchTicker && !matchCompany) return false;
    }
    return true;
  });
}
