'use client';

import React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Edit3,
  FileText,
  Loader2,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { formatCurrency } from '@/lib/formatters';
import type { Language } from '@/lib/translations';
import type { Position } from '@/lib/types';
import {
  DEFAULT_WATCHLIST_COLUMN_WIDTHS,
  formatDeclineToTarget,
  formatPercent,
  getQuoteTooltip,
  numericSortWithNulls,
  type TranslateFn,
} from '@/lib/watchlist-formatters';
import { InlineDateCell } from './InlineDateCell';

function ColumnSortIndicator({
  column,
}: {
  column: { getIsSorted: () => false | 'asc' | 'desc' };
}) {
  const sorted = column.getIsSorted();
  if (sorted === 'asc') {
    return <ArrowUp className="w-3 h-3 text-emerald-400 shrink-0" />;
  }
  if (sorted === 'desc') {
    return <ArrowDown className="w-3 h-3 text-emerald-400 shrink-0" />;
  }
  return (
    <ArrowUpDown className="w-3 h-3 opacity-40 shrink-0 group-hover:opacity-80 transition-opacity" />
  );
}

export interface BuildWatchlistColumnsParams {
  editingDateTicker: string | null;
  updatingDateTickers: Set<string>;
  handleStartEditingDate: (ticker: string, currentDate: string | null) => void;
  handleCancelEditingDate: () => void;
  handleSaveDate: (
    ticker: string,
    newDate: string,
    originalDate: string | null,
    currency: string
  ) => void;
  refreshingTickers: Set<string>;
  batchRefreshing: boolean;
  handleSingleRefresh: (ticker: string) => void;
  onEditTicker?: (ticker: string) => void;
  expandedDescriptionTickers: Set<string>;
  toggleDescription: (ticker: string) => void;
  language: Language;
  t: TranslateFn;
}

export function buildWatchlistColumns({
  editingDateTicker,
  updatingDateTickers,
  handleStartEditingDate,
  handleCancelEditingDate,
  handleSaveDate,
  refreshingTickers,
  batchRefreshing,
  handleSingleRefresh,
  onEditTicker,
  expandedDescriptionTickers,
  toggleDescription,
  language,
  t,
}: BuildWatchlistColumnsParams): ColumnDef<Position>[] {
  return [
    {
      accessorKey: 'analysis_date',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.analysis_date,
      minSize: 70,
      maxSize: 160,
      sortingFn: (rowA, rowB, columnId) => {
        const a = rowA.getValue<string | null>(columnId);
        const b = rowB.getValue<string | null>(columnId);
        if (!a && !b) return 0;
        if (!a) return 1;
        if (!b) return -1;
        return String(a).localeCompare(String(b));
      },
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center justify-center gap-1 mx-auto hover:text-white transition-colors uppercase tracking-wider select-none text-center group/th-date text-inherit cursor-pointer"
          title={t('sortByAnalysisDate')}
        >
          <div className="flex flex-col items-center leading-tight [word-break:keep-all] whitespace-normal">
            <span>{t('colAnalysis')}</span>
            <span className="text-[0.9em] text-zinc-400 font-medium">{t('colDate')}</span>
          </div>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const pos = row.original;
        const ticker = pos.user_ticker;
        return (
          <InlineDateCell
            ticker={ticker}
            analysisDate={pos.analysis_date}
            currency={pos.currency}
            isEditing={editingDateTicker === ticker}
            isUpdating={updatingDateTickers.has(ticker)}
            t={t}
            onStartEditing={handleStartEditingDate}
            onCancelEditing={handleCancelEditingDate}
            onSaveDate={handleSaveDate}
          />
        );
      },
    },
    {
      accessorKey: 'user_ticker',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.user_ticker,
      minSize: 70,
      maxSize: 350,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal">{t('colTicker')}</span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const pos = row.original;
        const isTargetReached =
          pos.target_price !== null &&
          pos.latest_price !== null &&
          pos.target_price > 0 &&
          pos.latest_price > 0 &&
          pos.latest_price <= pos.target_price;

        if (isTargetReached) {
          return (
            <div
              className="inline-flex flex-col px-2 py-1 rounded-lg bg-emerald-500/20 border border-emerald-400/50 shadow-[0_0_12px_rgba(16,185,129,0.35)] transition-all"
              title={t('targetReachedTooltip', {
                price: formatCurrency(pos.latest_price, pos.currency, language),
                target: formatCurrency(pos.target_price, pos.currency, language),
              })}
            >
              <div className="flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping motion-reduce:animate-none absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
                </span>
                <span className="font-bold text-emerald-200 tracking-wide font-mono text-xs">
                  {pos.user_ticker}
                </span>
              </div>
              {pos.provider_symbol && pos.provider_symbol !== pos.user_ticker && (
                <span className="text-[10px] text-emerald-400/80 font-mono pl-3.5 leading-none">
                  {pos.provider_symbol}
                </span>
              )}
            </div>
          );
        }

        return (
          <div className="flex flex-col">
            <span className="font-semibold text-white tracking-wide font-mono leading-tight">
              {pos.user_ticker}
            </span>
            {pos.provider_symbol && pos.provider_symbol !== pos.user_ticker && (
              <span className="text-[11px] text-zinc-500 font-mono leading-none mt-0.5">
                {pos.provider_symbol}
              </span>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'company_name',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.company_name,
      minSize: 85,
      maxSize: 600,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal">{t('colCompany')}</span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => (
        <span
          className="text-zinc-200 font-medium truncate block w-full"
          title={row.original.company_name}
        >
          {row.original.company_name || '—'}
        </span>
      ),
    },
    {
      accessorKey: 'exchange',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.exchange,
      minSize: 65,
      maxSize: 220,
      header: () => (
        <span className="uppercase tracking-wider text-inherit [word-break:keep-all] whitespace-normal">
          {t('colExchange')}
        </span>
      ),
      cell: ({ row }) => (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-mono bg-zinc-800 text-zinc-300 border border-zinc-700/60 leading-none">
          {row.original.exchange || 'AUTO'}
        </span>
      ),
    },
    {
      accessorKey: 'currency',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.currency,
      minSize: 52,
      maxSize: 160,
      header: () => (
        <span className="uppercase tracking-wider text-inherit [word-break:keep-all] whitespace-normal">
          {t('colCurrency')}
        </span>
      ),
      cell: ({ row }) => (
        <span className="text-xs font-mono text-zinc-400">
          {row.original.currency || '—'}
        </span>
      ),
    },
    {
      accessorKey: 'latest_price',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.latest_price,
      minSize: 76,
      maxSize: 320,
      sortingFn: numericSortWithNulls,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal text-right">
            {t('colLastPrice')}
          </span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const pos = row.original;
        return (
          <div
            className="flex items-center justify-end font-mono font-medium text-white tabular-nums leading-tight"
            title={getQuoteTooltip(pos, t)}
            onMouseEnter={(event) => {
              event.currentTarget.title = getQuoteTooltip(pos, t, Date.now()) ?? '';
            }}
          >
            {formatCurrency(pos.latest_price, pos.currency, language)}
          </div>
        );
      },
    },
    {
      accessorKey: 'daily_variation',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.daily_variation,
      minSize: 70,
      maxSize: 260,
      sortingFn: numericSortWithNulls,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal text-right">
            {t('colDayVar')}
          </span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const { text, colorClass } = formatPercent(
          row.original.daily_variation,
          row.original.daily_variation_valid
        );
        return (
          <div className="flex items-center justify-end gap-1">
            {row.original.daily_variation_valid &&
              row.original.daily_variation !== null &&
              (row.original.daily_variation >= 0 ? (
                <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
              ))}
            <span className={colorClass}>{text}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'ytd_variation',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.ytd_variation,
      minSize: 64,
      maxSize: 320,
      sortingFn: numericSortWithNulls,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal text-right">
            {t('colYtdVar')}
          </span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const { text, colorClass } = formatPercent(
          row.original.ytd_variation,
          row.original.ytd_variation_valid
        );
        return (
          <div className="flex items-center justify-end">
            <span className={colorClass}>{text}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'variation_since_analysis',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.variation_since_analysis,
      minSize: 80,
      maxSize: 320,
      sortingFn: numericSortWithNulls,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal text-right">
            {t('colAnalysisVar')}
          </span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const { text, colorClass } = formatPercent(
          row.original.variation_since_analysis,
          row.original.variation_since_analysis_valid
        );
        return (
          <div className="flex items-center justify-end">
            <span className={colorClass}>{text}</span>
          </div>
        );
      },
    },
    {
      accessorFn: (row) =>
        row.decline_to_target_valid && row.decline_to_target !== null
          ? row.decline_to_target
          : null,
      id: 'decline_to_target',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.decline_to_target,
      minSize: 82,
      maxSize: 320,
      sortingFn: numericSortWithNulls,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal text-right">
            {t('colToTarget')}
          </span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => {
        const { text, colorClass } = formatDeclineToTarget(
          row.original.decline_to_target,
          row.original.decline_to_target_valid
        );
        return (
          <div className="flex items-center justify-end">
            <span className={colorClass}>{text}</span>
          </div>
        );
      },
    },
    {
      accessorKey: 'target_price',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.target_price,
      minSize: 76,
      maxSize: 260,
      sortingFn: numericSortWithNulls,
      header: ({ column }) => (
        <button
          type="button"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
        >
          <span className="[word-break:keep-all] whitespace-normal text-right">
            {t('colTargetPrice')}
          </span>
          <ColumnSortIndicator column={column} />
        </button>
      ),
      cell: ({ row }) => (
        <div className="flex justify-end font-mono text-zinc-300">
          {formatCurrency(row.original.target_price, row.original.currency, language)}
        </div>
      ),
    },
    {
      id: 'actions',
      size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.actions,
      minSize: 78,
      maxSize: 105,
      enableResizing: false,
      header: '',
      cell: ({ row }) => {
        const ticker = row.original.user_ticker;
        const isRefreshing = refreshingTickers.has(ticker);
        const isExpanded = expandedDescriptionTickers.has(ticker);
        const hasComment = Boolean(row.original.comment && row.original.comment.trim());

        return (
          <div className="flex items-center justify-end gap-0.5">
            {/* Description toggle button */}
            <button
              type="button"
              onClick={() => toggleDescription(ticker)}
              aria-label={t('toggleNotesAria', { ticker })}
              className={`p-1 rounded-lg transition-all relative ${
                isExpanded
                  ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                  : hasComment
                  ? 'text-blue-400 hover:text-blue-300 hover:bg-blue-500/10'
                  : 'text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800'
              }`}
              title={
                hasComment
                  ? t('notesPreviewTooltip', {
                      preview: `${row.original.comment.slice(0, 60)}${
                        row.original.comment.length > 60 ? '...' : ''
                      }`,
                    })
                  : t('addNotesTooltip', { ticker })
              }
            >
              <FileText className="w-3.5 h-3.5" />
              {hasComment && (
                <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-blue-400" />
              )}
            </button>

            {/* Edit instrument modal button */}
            <button
              type="button"
              onClick={() => onEditTicker?.(ticker)}
              aria-label={t('editTickerAria', { ticker })}
              className="p-1 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 transition-all"
              title={t('editTickerTooltip', { ticker })}
            >
              <Edit3 className="w-3.5 h-3.5" />
            </button>

            {/* Refresh quote button */}
            <button
              type="button"
              onClick={() => handleSingleRefresh(ticker)}
              disabled={isRefreshing || batchRefreshing}
              aria-label={t('refreshTickerAria', { ticker })}
              className="p-1 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-emerald-400 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
              title={t('refreshTickerTooltip', { ticker })}
            >
              {isRefreshing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none text-emerald-400" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
            </button>
          </div>
        );
      },
    },
  ];
}
