'use client';

import { useCallback, useState } from 'react';
import {
  fetchAnalysisPrice,
  getMetrics,
  getPositions,
  refreshInstrument,
  streamRefresh,
  updateInstrument,
  wipeDatabase,
} from '@/lib/api';
import { formatCurrency } from '@/lib/formatters';
import type { Language } from '@/lib/translations';
import type { TranslateFn } from '@/lib/watchlist-formatters';
import type { PortfolioMetrics, Position, RefreshProgressEvent } from '@/lib/types';

const getErrorMessage = (err: unknown): string => (err instanceof Error ? err.message : String(err));

interface PortfolioContextLike {
  setPositions: (positions: Position[]) => void;
  setMetrics: (metrics: PortfolioMetrics | null) => void;
  optimisticUpdatePosition: (ticker: string, patch: Partial<Position>) => () => void;
  refreshPortfolioData: (options?: { silent?: boolean }) => Promise<void>;
}

interface UseWatchlistActionsParams {
  data: Position[];
  setData: (positions: Position[]) => void;
  activeMetrics: PortfolioMetrics | null;
  portfolioContext: PortfolioContextLike | null;
  onDataChange?: (positions: Position[], metrics: PortfolioMetrics | null) => void;
  addToast: (type: 'success' | 'error' | 'info', message: string) => void;
  language: Language;
  t: TranslateFn;
}

export function useWatchlistActions({
  data,
  setData,
  activeMetrics,
  portfolioContext,
  onDataChange,
  addToast,
  language,
  t,
}: UseWatchlistActionsParams) {
  const [batchRefreshing, setBatchRefreshing] = useState(false);
  const [refreshingTickers, setRefreshingTickers] = useState<Set<string>>(new Set());
  const [wipeModalOpen, setWipeModalOpen] = useState(false);
  const [wipingDb, setWipingDb] = useState(false);
  const [expandedDescriptionTickers, setExpandedDescriptionTickers] = useState<Set<string>>(new Set());
  const [editingDateTicker, setEditingDateTicker] = useState<string | null>(null);
  const [updatingDateTickers, setUpdatingDateTickers] = useState<Set<string>>(new Set());

  const handleStartEditingDate = useCallback((ticker: string) => setEditingDateTicker(ticker), []);
  const handleCancelEditingDate = useCallback(() => setEditingDateTicker(null), []);

  const toggleDescription = useCallback((ticker: string) => {
    setExpandedDescriptionTickers((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) next.delete(ticker);
      else next.add(ticker);
      return next;
    });
  }, []);

  const applyOptimisticUpdate = useCallback(
    (ticker: string, patch: Partial<Position>) => {
      const rollback = portfolioContext?.optimisticUpdatePosition(ticker, patch);
      const updated = data.map((item) => (item.user_ticker === ticker ? { ...item, ...patch } : item));
      setData(updated);
      if (!portfolioContext) onDataChange?.(updated, activeMetrics);
      return () => {
        rollback?.();
        if (!portfolioContext) {
          setData(data);
          onDataChange?.(data, activeMetrics);
        }
      };
    },
    [portfolioContext, data, setData, onDataChange, activeMetrics]
  );

  const refreshPortfolioData = portfolioContext?.refreshPortfolioData;

  const reloadData = useCallback(async () => {
    if (refreshPortfolioData) {
      await refreshPortfolioData({ silent: true });
      return;
    }
    try {
      const [posResult, metricsResult] = await Promise.allSettled([getPositions(), getMetrics()]);
      const newPositions = posResult.status === 'fulfilled' ? posResult.value.positions || [] : [];
      const newMetrics = metricsResult.status === 'fulfilled' ? metricsResult.value : null;
      setData(newPositions);
      onDataChange?.(newPositions, newMetrics);
    } catch {
      // Silently handle — the toast from the caller is sufficient
    }
  }, [refreshPortfolioData, setData, onDataChange]);

  const handleSaveComment = useCallback(
    async (pos: Position, newComment: string) => {
      const ticker = pos.user_ticker;
      const rollback = applyOptimisticUpdate(ticker, { comment: newComment });
      try {
        await updateInstrument(ticker, { comment: newComment });
        addToast('success', t('notesSavedToast', { ticker }));
        portfolioContext?.refreshPortfolioData({ silent: true });
      } catch (err) {
        rollback();
        addToast('error', t('notesSaveErrorToast', { ticker, error: getErrorMessage(err) }));
      }
    },
    [applyOptimisticUpdate, addToast, portfolioContext, t]
  );

  const handleSaveDate = useCallback(
    async (ticker: string, newDate: string, originalDate: string | null, currency: string) => {
      const cleanNewDate = newDate.trim() || null;
      const cleanOriginalDate = originalDate?.trim() || null;
      setEditingDateTicker(null);
      if (cleanNewDate === cleanOriginalDate) return;

      setUpdatingDateTickers((prev) => new Set(prev).add(ticker));
      const rollback = applyOptimisticUpdate(ticker, { analysis_date: cleanNewDate });
      try {
        await updateInstrument(ticker, { analysis_date: cleanNewDate });
        if (cleanNewDate) {
          try {
            const histRes = await fetchAnalysisPrice(ticker, cleanNewDate);
            addToast(
              'success',
              t('dateUpdatedToast', {
                ticker,
                date: cleanNewDate,
                price: formatCurrency(histRes.analysis_reference_price, currency, language),
              })
            );
          } catch (priceErr) {
            addToast(
              'info',
              t('dateSavedNoYahooToast', { ticker, date: cleanNewDate, error: getErrorMessage(priceErr) })
            );
          }
        } else {
          addToast('success', t('dateRemovedToast', { ticker }));
        }
        await reloadData();
      } catch (err) {
        rollback();
        addToast('error', t('dateUpdateErrorToast', { ticker, error: getErrorMessage(err) }));
      } finally {
        setUpdatingDateTickers((prev) => {
          const next = new Set(prev);
          next.delete(ticker);
          return next;
        });
      }
    },
    [applyOptimisticUpdate, addToast, reloadData, language, t]
  );

  const handleBatchRefresh = useCallback(
    async (onProgress?: (event: RefreshProgressEvent) => void) => {
      if (batchRefreshing) return;
      setBatchRefreshing(true);
      try {
        let completed = false;
        const quotesRes = await streamRefresh((event) => {
          if (event.type === 'complete') completed = true;
          onProgress?.(event);
        });
        if (!onProgress || !completed) await reloadData();
        if (quotesRes.status === 'fresh') {
          addToast('info', quotesRes.message || t('quotesFreshToast'));
          return;
        }
        const failed = quotesRes.failed ?? 0;
        const analysis = quotesRes.analysis_prices_updated ?? 0;
        const ytd = quotesRes.ytd_prices_updated ?? 0;
        addToast(
          failed > 0 ? 'info' : 'success',
          t('batchRefreshSummaryToast', {
            updated: quotesRes.updated ?? 0,
            total: quotesRes.total ?? 0,
            failedPart: failed > 0 ? t('batchRefreshFailedPart', { count: failed }) : '',
            analysisPart: analysis > 0 ? t('batchRefreshAnalysisPart', { count: analysis }) : '',
            ytdPart: ytd > 0 ? t('batchRefreshYtdPart', { count: ytd }) : '',
          })
        );
      } catch (err) {
        addToast('error', t('batchRefreshErrorToast', { error: getErrorMessage(err) }));
      } finally {
        setBatchRefreshing(false);
      }
    },
    [batchRefreshing, addToast, reloadData, t]
  );

  const handleSingleRefresh = useCallback(
    async (ticker: string) => {
      if (refreshingTickers.has(ticker)) return;
      setRefreshingTickers((prev) => new Set(prev).add(ticker));
      try {
        const result = await refreshInstrument(ticker);
        if (result.status === 'ok') {
          addToast('success', t('singleQuoteUpdatedToast', { ticker }));
        } else if (result.status === 'fresh') {
          addToast('info', `${ticker}: ${result.message || t('singleQuoteFreshFallback')}`);
        } else {
          addToast('info', `${ticker}: ${result.detail || t('singleQuoteUnavailableFallback')}`);
        }
        await reloadData();
      } catch (err) {
        addToast('error', t('singleQuoteErrorToast', { ticker, error: getErrorMessage(err) }));
      } finally {
        setRefreshingTickers((prev) => {
          const next = new Set(prev);
          next.delete(ticker);
          return next;
        });
      }
    },
    [refreshingTickers, addToast, reloadData, t]
  );

  const handleWipeDatabase = useCallback(async () => {
    setWipingDb(true);
    try {
      await wipeDatabase();
      addToast('success', t('databaseWipedToast'));
      setData([]);
      if (portfolioContext) {
        portfolioContext.setPositions([]);
        portfolioContext.setMetrics(null);
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      onDataChange?.([], null);
    } catch (err) {
      addToast('error', t('databaseWipeErrorToast', { error: getErrorMessage(err) }));
    } finally {
      setWipingDb(false);
      setWipeModalOpen(false);
    }
  }, [addToast, onDataChange, portfolioContext, setData, t]);

  return {
    batchRefreshing,
    refreshingTickers,
    wipeModalOpen,
    setWipeModalOpen,
    wipingDb,
    expandedDescriptionTickers,
    editingDateTicker,
    updatingDateTickers,
    handleStartEditingDate,
    handleCancelEditingDate,
    toggleDescription,
    reloadData,
    handleSaveComment,
    handleSaveDate,
    handleBatchRefresh,
    handleSingleRefresh,
    handleWipeDatabase,
  };
}
