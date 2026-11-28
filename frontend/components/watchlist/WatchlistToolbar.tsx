'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Download,
  Filter,
  Loader2,
  PlusCircle,
  RefreshCw,
  RotateCcw,
  Rows3,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { usePortfolioRefreshOptional } from '@/context/PortfolioRefreshContext';
import { useLanguage } from '@/context/LanguageContext';
import type { TranslationKey } from '@/lib/translations';
import type { AppConfig, RefreshProgressEvent } from '@/lib/types';
import { RowHeightPopover } from './RowHeightPopover';

export interface ToolbarConfig {
  updateQuotes: boolean;
  addInstrument: boolean;
  restoreColumns: boolean;
  rowHeight: boolean;
  exportBackup: boolean;
  importValues: boolean;
  wipeDatabase: boolean;
}

export const DEFAULT_TOOLBAR_CONFIG: ToolbarConfig = {
  updateQuotes: true,
  addInstrument: true,
  restoreColumns: true,
  rowHeight: false,
  exportBackup: true,
  importValues: false,
  wipeDatabase: false,
};

export const TOOLBAR_STORAGE_KEY = 'portfoliomaster_toolbar_config';

export function isPartialToolbarConfig(value: unknown): value is Partial<ToolbarConfig> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }
  return Object.entries(value as Record<string, unknown>).every(
    ([key, val]) => key in DEFAULT_TOOLBAR_CONFIG && typeof val === 'boolean'
  );
}

const TOOLBAR_ITEMS: Array<{
  key: keyof ToolbarConfig;
  labelKey: TranslationKey;
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
}> = [
  {
    key: 'updateQuotes',
    labelKey: 'refreshQuotes',
    icon: RefreshCw,
    iconColor: 'text-emerald-400',
  },
  {
    key: 'addInstrument',
    labelKey: 'addInstrument',
    icon: PlusCircle,
    iconColor: 'text-emerald-400',
  },
  {
    key: 'restoreColumns',
    labelKey: 'resetColumns',
    icon: RotateCcw,
    iconColor: 'text-zinc-400',
  },
  {
    key: 'rowHeight',
    labelKey: 'rowHeightLabel',
    icon: Rows3,
    iconColor: 'text-indigo-400',
  },
  {
    key: 'exportBackup',
    labelKey: 'exportBackupLabel',
    icon: Download,
    iconColor: 'text-blue-400',
  },
  {
    key: 'importValues',
    labelKey: 'importValuesLabel',
    icon: Upload,
    iconColor: 'text-emerald-400',
  },
  {
    key: 'wipeDatabase',
    labelKey: 'wipeDatabaseLabel',
    icon: Trash2,
    iconColor: 'text-rose-400',
  },
];

export interface WatchlistToolbarProps {
  globalFilter: string;
  onGlobalFilterChange: (value: string) => void;
  selectedExchange: string;
  onSelectedExchangeChange: (value: string) => void;
  exchanges: string[];
  selectedCurrency: string;
  onSelectedCurrencyChange: (value: string) => void;
  currencies: string[];
  filteredCount: number;
  totalCount: number;
  toolbarConfig: ToolbarConfig;
  onToggleToolbarAction: (key: keyof ToolbarConfig) => void;
  onResetToolbarConfig: () => void;
  hasCustomColumnSizing: boolean;
  onResetColumnWidths: () => void;
  rowHeight: number;
  onRowHeightChange: (newHeight: number) => void;
  appConfig?: AppConfig | null;
  batchRefreshing: boolean;
  wipingDb: boolean;
  onBatchRefresh: (onProgress?: (event: RefreshProgressEvent) => void) => Promise<void>;
  onOpenBackupModal: () => void;
  onOpenWipeModal: () => void;
  onAddInstrument?: () => void;
}

function WatchlistRefreshButton({
  appConfig,
  batchRefreshing,
  isEmpty,
  onRefresh,
}: {
  appConfig?: AppConfig | null;
  batchRefreshing: boolean;
  isEmpty: boolean;
  onRefresh: (onProgress?: (event: RefreshProgressEvent) => void) => Promise<void>;
}) {
  const refresh = usePortfolioRefreshOptional();
  const { t } = useLanguage();
  const config = refresh?.config ?? appConfig;
  const isAnyRefreshing =
    batchRefreshing || (refresh ? refresh.isRefreshing : Boolean(config?.is_refreshing));
  const currentBatch = refresh?.batchProgress?.currentBatch ?? config?.current_batch ?? 0;
  const totalBatches = refresh?.batchProgress?.totalBatches ?? config?.total_batches ?? 0;
  const processed = refresh?.batchProgress?.processed ?? config?.processed_symbols ?? 0;
  const total = refresh?.batchProgress?.total ?? config?.total_symbols ?? 0;

  return (
    <button
      type="button"
      onClick={() => onRefresh(refresh?.applyStreamEvent)}
      disabled={isAnyRefreshing || isEmpty}
      aria-label={t('refreshQuotes')}
      className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
        bg-emerald-500/10 text-emerald-400 border border-emerald-500/20
        hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/40
        disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
      title={t('refreshQuotesTooltip')}
    >
      {isAnyRefreshing ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none text-amber-400" />
          <span className="hidden sm:inline text-amber-300">
            {currentBatch > 0 && totalBatches > 0
              ? t('updatingProgress', {
                  current: currentBatch,
                  total: totalBatches,
                  processed,
                  symbols: total,
                })
              : t('refreshing')}
          </span>
        </>
      ) : (
        <>
          <RefreshCw className="w-4 h-4" />
          <span className="hidden sm:inline">{t('refreshQuotes')}</span>
        </>
      )}
    </button>
  );
}

export function WatchlistToolbar({
  globalFilter,
  onGlobalFilterChange,
  selectedExchange,
  onSelectedExchangeChange,
  exchanges,
  selectedCurrency,
  onSelectedCurrencyChange,
  currencies,
  filteredCount,
  totalCount,
  toolbarConfig,
  onToggleToolbarAction,
  onResetToolbarConfig,
  hasCustomColumnSizing,
  onResetColumnWidths,
  rowHeight,
  onRowHeightChange,
  appConfig,
  batchRefreshing,
  wipingDb,
  onBatchRefresh,
  onOpenBackupModal,
  onOpenWipeModal,
  onAddInstrument,
}: WatchlistToolbarProps) {
  const router = useRouter();
  const { t } = useLanguage();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!settingsOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSettingsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [settingsOpen]);

  return (
    <div className="relative z-30 flex flex-col 2xl:flex-row items-stretch 2xl:items-center justify-between gap-3 bg-zinc-900/80 backdrop-blur border border-zinc-800 p-2.5 sm:p-3 rounded-xl">
      {/* Left side: Search & Filter Controls */}
      <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
        {/* Search Input */}
        <div className="relative min-w-[160px] sm:min-w-[200px] max-w-xs flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
          <input
            type="text"
            aria-label={t('searchAria')}
            placeholder={t('searchPlaceholder')}
            value={globalFilter}
            onChange={(e) => onGlobalFilterChange(e.target.value)}
            className="w-full bg-zinc-950/70 border border-zinc-800 rounded-lg pl-9 pr-3 py-1.5 text-xs sm:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 transition-all font-sans h-9"
          />
        </div>

        {/* Mercado Filter */}
        <div className="flex items-center gap-1.5 bg-zinc-950/50 border border-zinc-800 rounded-lg px-2.5 h-9 shrink-0">
          <Filter className="w-3.5 h-3.5 text-zinc-400" />
          <label htmlFor="watchlist-exchange-filter" className="text-xs text-zinc-400">
            {t('exchangeFilterLabel')}
          </label>
          <select
            id="watchlist-exchange-filter"
            aria-label={t('exchangeFilterAria')}
            value={selectedExchange}
            onChange={(e) => onSelectedExchangeChange(e.target.value)}
            className="bg-transparent text-xs text-zinc-200 font-medium focus:outline-none cursor-pointer pr-1"
          >
            <option value="ALL" className="bg-zinc-900 text-zinc-200">
              {t('allExchanges')}
            </option>
            {exchanges.map((ex) => (
              <option key={ex} value={ex} className="bg-zinc-900 text-zinc-200">
                {ex}
              </option>
            ))}
          </select>
        </div>

        {/* Divisa Filter */}
        <div className="flex items-center gap-1.5 bg-zinc-950/50 border border-zinc-800 rounded-lg px-2.5 h-9 shrink-0">
          <label htmlFor="watchlist-currency-filter" className="text-xs text-zinc-400">
            {t('currencyFilterLabel')}
          </label>
          <select
            id="watchlist-currency-filter"
            aria-label={t('currencyFilterAria')}
            value={selectedCurrency}
            onChange={(e) => onSelectedCurrencyChange(e.target.value)}
            className="bg-transparent text-xs text-zinc-200 font-medium focus:outline-none cursor-pointer pr-1"
          >
            <option value="ALL" className="bg-zinc-900 text-zinc-200">
              {t('allCurrencies')}
            </option>
            {currencies.map((curr) => (
              <option key={curr} value={curr} className="bg-zinc-900 text-zinc-200">
                {curr}
              </option>
            ))}
          </select>
        </div>

        {/* Counter Badge */}
        <div className="inline-flex items-center text-xs text-zinc-400 px-2.5 h-9 font-mono whitespace-nowrap shrink-0 bg-zinc-950/40 border border-zinc-800/80 rounded-lg">
          {t('showingLabel')}{' '}
          <span className="text-zinc-200 font-semibold mx-1">{filteredCount}</span>{' '}
          {t('ofLabel')}{' '}
          <span className="text-zinc-200 font-semibold ml-1">{totalCount}</span>
        </div>
      </div>

      {/* Right side: Action Buttons */}
      <div className="flex items-center gap-2 shrink-0 flex-wrap">
        {/* Add Instrument Button */}
        {toolbarConfig.addInstrument && onAddInstrument && (
          <button
            type="button"
            onClick={onAddInstrument}
            className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
              bg-zinc-800/90 text-zinc-200 border border-zinc-700
              hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
            title={t('addInstrumentTooltip')}
          >
            <PlusCircle className="w-4 h-4 text-emerald-400" />
            <span className="hidden sm:inline">{t('addInstrument')}</span>
          </button>
        )}

        {/* Quick Import Values Button */}
        {toolbarConfig.importValues && (
          <button
            type="button"
            onClick={() => router.push('/import')}
            className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
              bg-zinc-800/90 text-zinc-200 border border-zinc-700
              hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
            title={t('importValuesTooltip')}
          >
            <Upload className="w-4 h-4 text-emerald-400" />
            <span className="hidden sm:inline">{t('import')}</span>
          </button>
        )}

        {/* Export / Backup Button */}
        {toolbarConfig.exportBackup && (
          <button
            type="button"
            onClick={onOpenBackupModal}
            className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
              bg-zinc-800/90 text-zinc-200 border border-zinc-700
              hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
            title={t('exportBackupTooltip')}
          >
            <Download className="w-4 h-4 text-blue-400" />
            <span className="hidden sm:inline">{t('exportBackupLabel')}</span>
          </button>
        )}

        {/* Batch Refresh */}
        {toolbarConfig.updateQuotes && (
          <WatchlistRefreshButton
            appConfig={appConfig}
            batchRefreshing={batchRefreshing}
            isEmpty={totalCount === 0}
            onRefresh={onBatchRefresh}
          />
        )}

        {/* Reset Column Widths Button */}
        {toolbarConfig.restoreColumns && (
          <button
            type="button"
            onClick={onResetColumnWidths}
            disabled={!hasCustomColumnSizing}
            className={`h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all shrink-0 border ${
              hasCustomColumnSizing
                ? 'bg-zinc-800 text-zinc-200 border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm cursor-pointer'
                : 'bg-zinc-900/40 text-zinc-600 border-zinc-800/60 cursor-not-allowed opacity-50'
            }`}
            title={
              hasCustomColumnSizing
                ? t('resetColumnsTooltip')
                : t('columnsAlreadyDefaultTooltip')
            }
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span className="hidden xl:inline">{t('resetColumns')}</span>
          </button>
        )}

        {/* Row Height Controller Button & Popover */}
        {toolbarConfig.rowHeight && (
          <RowHeightPopover
            rowHeight={rowHeight}
            onRowHeightChange={onRowHeightChange}
          />
        )}

        {/* Wipe Database */}
        {toolbarConfig.wipeDatabase && (
          <button
            type="button"
            onClick={onOpenWipeModal}
            disabled={batchRefreshing || wipingDb}
            className="h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all
              bg-rose-500/5 text-zinc-500 border border-zinc-800
              hover:bg-rose-500/10 hover:text-rose-400 hover:border-rose-500/30
              disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
            title={t('wipeDatabaseTooltip')}
          >
            <Trash2 className="w-4 h-4" />
            <span className="hidden sm:inline">{t('wipeDb')}</span>
          </button>
        )}

        {/* Settings / Customize Toolbar Popover */}
        <div className="relative" ref={settingsRef}>
          <button
            type="button"
            onClick={() => setSettingsOpen((prev) => !prev)}
            aria-label={t('customizeToolbarAria')}
            aria-expanded={settingsOpen}
            className={`h-9 w-9 inline-flex items-center justify-center rounded-lg text-xs font-medium transition-all shrink-0 border cursor-pointer ${
              settingsOpen
                ? 'bg-zinc-800 text-emerald-400 border-zinc-600 ring-1 ring-emerald-500/40'
                : 'bg-zinc-800/90 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm'
            }`}
            title={t('customizeToolbarTooltip')}
          >
            <SlidersHorizontal className="w-4 h-4" />
          </button>

          {settingsOpen && (
            <div className="absolute right-0 top-full mt-2 w-[calc(100vw-2rem)] sm:w-80 rounded-xl bg-zinc-900 border border-zinc-800 shadow-2xl p-3.5 z-[100] animate-in fade-in zoom-in-95 motion-reduce:animate-none duration-150">
              <div className="flex items-center justify-between pb-2.5 border-b border-zinc-800/80">
                <div className="flex items-center gap-2">
                  <SlidersHorizontal className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-xs font-semibold text-white tracking-tight">
                    {t('customizeToolbar')}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setSettingsOpen(false)}
                  aria-label={t('closeToolbarSettingsAria')}
                  className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60 transition-colors cursor-pointer"
                  title={t('close')}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <p className="text-[11px] text-zinc-400 mt-2 mb-2 leading-relaxed">
                {t('customizeToolbarDesc')}
              </p>

              <div className="space-y-1">
                {TOOLBAR_ITEMS.map((item) => {
                  const isEnabled = toolbarConfig[item.key];
                  const Icon = item.icon;
                  const itemLabel = t(item.labelKey);

                  return (
                    <button
                      key={item.key}
                      type="button"
                      role="switch"
                      aria-checked={isEnabled}
                      onClick={() => onToggleToolbarAction(item.key)}
                      className="w-full flex items-center justify-between p-2 rounded-lg hover:bg-zinc-800/60 cursor-pointer select-none transition-colors group text-left"
                    >
                      <div className="flex items-center gap-2.5 min-w-0 pr-2">
                        <Icon className={`w-3.5 h-3.5 shrink-0 ${item.iconColor}`} />
                        <span className="text-xs text-zinc-300 group-hover:text-white font-medium truncate">
                          {itemLabel}
                        </span>
                      </div>
                      <div
                        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors motion-reduce:transition-none duration-200 ease-in-out ${
                          isEnabled ? 'bg-emerald-600' : 'bg-zinc-800 border border-zinc-700'
                        }`}
                      >
                        <span
                          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-md ring-0 transition motion-reduce:transition-none duration-200 ease-in-out ${
                            isEnabled ? 'translate-x-4' : 'translate-x-0'
                          }`}
                        />
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="pt-2.5 mt-2 border-t border-zinc-800/80 flex items-center justify-between">
                <button
                  type="button"
                  onClick={onResetToolbarConfig}
                  className="text-[11px] text-zinc-400 hover:text-emerald-400 font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
                  title={t('resetToolbarTooltip')}
                >
                  <RotateCcw className="w-3 h-3" />
                  <span>{t('resetDefaults')}</span>
                </button>
                <span className="text-[10px] text-zinc-600 font-mono">localStorage</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
