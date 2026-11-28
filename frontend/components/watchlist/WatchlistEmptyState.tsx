'use client';

import React from 'react';
import { Info, Loader2, LogIn, PlusCircle } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';

export interface WatchlistEmptyStateProps {
  colSpan: number;
  hasRows: boolean;
  totalDataCount: number;
  isUnauthenticatedEmpty: boolean;
  isInitializing: boolean;
  onOpenAuthModal: () => void;
  onAddInstrument?: () => void;
}

export function WatchlistEmptyState({
  colSpan,
  hasRows,
  totalDataCount,
  isUnauthenticatedEmpty,
  isInitializing,
  onOpenAuthModal,
  onAddInstrument,
}: WatchlistEmptyStateProps) {
  const { t } = useLanguage();

  return (
    <tbody className="font-sans">
      {!hasRows && (
        <tr>
          <td colSpan={colSpan} className="py-12 sm:py-16 px-4 text-center text-zinc-400">
            {isUnauthenticatedEmpty ? (
              <div className="sticky left-4 sm:static flex flex-col items-center justify-center gap-3 max-w-[calc(100vw-3rem)] sm:max-w-sm mx-auto py-4">
                <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shadow-sm">
                  <LogIn className="w-6 h-6" />
                </div>
                <p className="text-sm font-semibold text-white">{t('signInPortfolioTitle')}</p>
                <p className="text-xs text-zinc-400 text-center leading-relaxed">{t('signInPortfolioDesc')}</p>
                <button
                  type="button"
                  onClick={onOpenAuthModal}
                  className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-zinc-950 bg-emerald-400 hover:bg-emerald-300 transition-colors shadow-lg shadow-emerald-950/40"
                >
                  <LogIn className="w-4 h-4" />
                  {t('signIn')}
                </button>
              </div>
            ) : isInitializing ? (
              <div className="sticky left-4 sm:static flex flex-col items-center justify-center gap-2.5 max-w-[calc(100vw-3rem)] sm:max-w-sm mx-auto">
                <Loader2 className="w-8 h-8 text-emerald-400 animate-spin motion-reduce:animate-none" />
                <p className="text-sm font-medium text-zinc-300">{t('loadingWatchlist')}</p>
                <p className="text-xs text-zinc-500">{t('syncingQuotes')}</p>
              </div>
            ) : (
              <div className="sticky left-4 sm:static flex flex-col items-center justify-center gap-2.5 max-w-[calc(100vw-3rem)] sm:max-w-sm mx-auto">
                <Info className="w-8 h-8 text-zinc-600" />
                <p className="text-sm font-medium text-zinc-300">
                  {totalDataCount === 0 ? t('emptyWatchlist') : t('emptyFilters')}
                </p>
                <p className="text-xs text-zinc-500">
                  {totalDataCount === 0 ? t('emptyWatchlistHint') : t('emptyFiltersHint')}
                </p>
                {totalDataCount === 0 && onAddInstrument && (
                  <button
                    type="button"
                    onClick={onAddInstrument}
                    className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-950/40"
                  >
                    <PlusCircle className="w-4 h-4" />
                    {t('addFirstInstrument')}
                  </button>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
      {onAddInstrument && (
        <tr
          onClick={onAddInstrument}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onAddInstrument();
            }
          }}
          tabIndex={0}
          role="button"
          className="group cursor-pointer border-t-2 border-dashed border-zinc-800/80 bg-zinc-950/30 hover:bg-emerald-500/[0.07] hover:border-emerald-500/30 transition-all select-none focus:outline-none focus:bg-emerald-500/[0.09]"
          title={t('addNewInstrumentRowTitle')}
        >
          <td colSpan={colSpan} className="py-3 px-4 text-left">
            <div className="flex items-center gap-3">
              <span className="w-6 h-6 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center group-hover:bg-emerald-500/20 group-hover:border-emerald-500/40 group-hover:scale-105 motion-reduce:group-hover:scale-100 transition-all text-emerald-400 shrink-0">
                <PlusCircle className="w-3.5 h-3.5" />
              </span>
              <span className="text-xs font-semibold text-emerald-400 group-hover:text-emerald-300 transition-colors">
                {t('addNewInstrumentRow')}
              </span>
              <span className="hidden sm:inline text-[11px] text-zinc-500 group-hover:text-zinc-400 transition-colors">
                {t('addNewInstrumentRowHint')}
              </span>
            </div>
          </td>
        </tr>
      )}
    </tbody>
  );
}
