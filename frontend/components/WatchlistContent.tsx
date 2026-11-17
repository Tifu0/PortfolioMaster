'use client';

// 'use client' is required here because WatchlistContent coordinates shared
// reactive state between MetricCards, WatchlistTable, and ManualEntryModal.
// It also reads query parameters (?add=1 or ?edit=TICKER) to control modal visibility.

import React, { useCallback, useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { useSearchParams, useRouter } from 'next/navigation';
import { MetricCards } from '@/components/MetricCards';
import { WatchlistTable } from '@/components/WatchlistTable';
import { usePortfolioData } from '@/context/PortfolioContext';
import { usePortfolioRefreshOptional } from '@/context/PortfolioRefreshContext';
import { useLanguage } from '@/context/LanguageContext';
import { useToast } from '@/components/ui/Toast';

const ManualEntryModal = dynamic(
  () => import('@/components/ManualEntryModal').then((mod) => mod.ManualEntryModal),
  { ssr: false }
);

export function WatchlistContent() {
  const { positions, metrics } = usePortfolioData();
  const { t } = useLanguage();

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [tickerToEdit, setTickerToEdit] = useState<string | null>(null);

  const router = useRouter();
  const searchParams = useSearchParams();
  const addToast = useToast();

  // Listen for ?add=1 or ?edit=TICKER in URL and custom header events
  useEffect(() => {
    const handleCheckUrl = () => {
      const currentSearchParams = new URLSearchParams(window.location.search);
      const addParam = currentSearchParams.get('add') || searchParams.get('add');
      const editParam = currentSearchParams.get('edit') || searchParams.get('edit');

      if (addParam === '1' || addParam === 'true') {
        setTickerToEdit(null);
        setIsModalOpen(true);
      } else if (editParam) {
        setTickerToEdit(editParam);
        setIsModalOpen(true);
      }
    };

    handleCheckUrl();

    const handleCustomOpenAdd = () => {
      setTickerToEdit(null);
      setIsModalOpen(true);
    };

    window.addEventListener('portfoliomaster:open-add', handleCustomOpenAdd);
    window.addEventListener('popstate', handleCheckUrl);

    return () => {
      window.removeEventListener('portfoliomaster:open-add', handleCustomOpenAdd);
      window.removeEventListener('popstate', handleCheckUrl);
    };
  }, [searchParams]);

  const handleOpenAdd = useCallback(() => {
    setTickerToEdit(null);
    setIsModalOpen(true);
  }, []);

  const handleOpenEdit = useCallback((ticker: string) => {
    setTickerToEdit(ticker);
    setIsModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setIsModalOpen(false);
    setTickerToEdit(null);
    // Clean URL query params without full reload
    if (searchParams.has('add') || searchParams.has('edit')) {
      router.replace('/', { scroll: false });
    }
  }, [router, searchParams]);

  const handleModalSuccess = useCallback((message: string) => {
    addToast('success', message);
  }, [addToast]);

  const handleModalError = useCallback(
    (message: string) => {
      addToast('error', message);
    },
    [addToast]
  );

  return (
    <>
      {/* Header section with page title & top-right runtime auto-refresh badge */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            {t('mainWatchlist')}
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            {t('mainWatchlistSubtitle')}
          </p>
        </div>

        <WatchlistRefreshBadge />
      </div>

      {/* Phase 4: Metric Cards */}
      <MetricCards metrics={metrics} positions={positions} />

      {/* Phase 3+6+7: Interactive Watchlist Table */}
      <WatchlistTable
        initialPositions={positions}
        initialMetrics={metrics}
        onEditTicker={handleOpenEdit}
        onAddInstrument={handleOpenAdd}
      />

      {/* Phase 7: Manual Entry / Edit Modal (Tab 2) */}
      <ManualEntryModal
        isOpen={isModalOpen}
        onClose={handleCloseModal}
        initialTickerToEdit={tickerToEdit}
        onSuccess={handleModalSuccess}
        onError={handleModalError}
      />
    </>
  );
}

function WatchlistRefreshBadge() {
  const refresh = usePortfolioRefreshOptional();
  const { t } = useLanguage();
  const appConfig = refresh?.config;
  if (!appConfig) return null;
  const isRefreshing = refresh.isRefreshing;
  const currentBatch = refresh.batchProgress?.currentBatch ?? 0;
  const totalBatches = refresh.batchProgress?.totalBatches ?? 0;
  const processed = refresh.batchProgress?.processed ?? 0;
  const total = refresh.batchProgress?.total ?? 0;
  return (
    <div
      key={isRefreshing ? 'badge-refreshing' : 'badge-idle'}
      translate="no"
      className={`notranslate flex items-center gap-2 self-start sm:self-auto px-3.5 py-1.5 rounded-full border text-xs font-mono shadow-sm backdrop-blur-sm transition-all duration-300 ${
        isRefreshing
          ? 'bg-amber-950/40 border-amber-500/40 text-amber-200'
          : 'bg-zinc-900/90 border-zinc-800 text-zinc-300'
      }`}
      title={
        isRefreshing
          ? t('refreshInProgress')
          : t('autoRefreshEvery', { seconds: appConfig.refresh_interval_seconds, size: appConfig.batch_size })
      }
    >
      {isRefreshing ? (
        <>
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
          </span>
          <span className="text-amber-400 font-semibold animate-pulse">
            {/* Actualizando lote... */}
            {currentBatch > 0 ? t('updatingBatch') : t('startingUpdate')}
          </span>
          <span className="text-zinc-600">·</span>
          <span className="text-amber-300/80">
            {currentBatch > 0 && totalBatches > 0 ? (
              <>
                <strong className="text-amber-200 font-semibold">
                  {currentBatch}/{totalBatches}
                </strong>{' '}
                <span>({processed}/{total})</span>
              </>
            ) : (
              <>
                <span>{t('batch')} </span>
                <strong className="text-amber-200 font-semibold">
                  {appConfig.batch_size}
                </strong>
              </>
            )}
          </span>
        </>
      ) : (
        <>
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span>
            <span>{t('autoSync')} </span>
            <strong className="text-emerald-400 font-semibold">
              {appConfig.refresh_interval_seconds}s
            </strong>
          </span>
          <span className="text-zinc-600">·</span>
          <span className="text-zinc-400">
            <span>{t('batch')} </span>
            <strong className="text-zinc-200 font-semibold">
              {appConfig.batch_size}
            </strong>
          </span>
        </>
      )}
    </div>
  );
}
