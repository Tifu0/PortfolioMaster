'use client';

import { createContext, use, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { authFetch, getConfig, refreshAll } from '@/lib/api';
import { startRefreshSync } from '@/lib/refresh-sync';
import type { AppConfig, Position, RefreshProgressEvent, RefreshStreamEvent } from '@/lib/types';

export function applyBatchQuotesDelta(
  positions: Position[],
  quotes: NonNullable<RefreshProgressEvent['quotes']>
): Position[] {
  let changed = false;
  const updated = positions.map((position) => {
    const symbol = (position.provider_symbol || position.user_ticker).trim().toUpperCase();
    const quote = quotes[symbol];
    if (quote?.price == null) return position;
    const latestPrice = Number(quote.price);
    if (!Number.isFinite(latestPrice)) return position;
    const previousClose = quote.previous_close == null ? position.previous_close : Number(quote.previous_close);
    const canCalculateVariation = previousClose != null && previousClose > 0 && latestPrice > 0;
    const nextEarningsDate =
      'earnings_date' in quote ? (quote.earnings_date ?? null) : position.earnings_date;
    changed = true;
    return {
      ...position,
      latest_price: latestPrice,
      previous_close: previousClose,
      daily_variation: canCalculateVariation ? Number((((latestPrice - previousClose) / previousClose) * 100).toFixed(2)) : position.daily_variation,
      daily_variation_valid: canCalculateVariation || position.daily_variation_valid,
      quote_status: quote.status ?? position.quote_status,
      quote_fetched_at: quote.quote_timestamp ?? position.quote_fetched_at,
      earnings_date: nextEarningsDate,
    };
  });
  return changed ? updated : positions;
}

interface BatchProgress {
  currentBatch: number;
  totalBatches: number;
  processed: number;
  total: number;
}

interface PortfolioRefresh {
  config: AppConfig | null;
  isRefreshing: boolean;
  batchProgress: BatchProgress | null;
  applyStreamEvent: (event: RefreshStreamEvent) => void;
}

const PortfolioRefreshContext = createContext<PortfolioRefresh | null>(null);

function readProgress(event: {
  batch_index?: number;
  total_batches?: number;
  processed_symbols?: number;
  total_symbols?: number;
}): BatchProgress | null {
  if (!event.total_batches) return null;
  return {
    currentBatch: event.batch_index ?? 0,
    totalBatches: event.total_batches,
    processed: event.processed_symbols ?? 0,
    total: event.total_symbols ?? 0,
  };
}

export function PortfolioRefreshProvider({ children, enabled, initialConfig, refreshPortfolioData, setPositions }: {
  children: ReactNode;
  enabled: boolean;
  initialConfig: AppConfig | null;
  refreshPortfolioData: () => Promise<void>;
  setPositions: Dispatch<SetStateAction<Position[]>>;
}) {
  const [config, setConfig] = useState(initialConfig);
  const [isRefreshing, setIsRefreshing] = useState(enabled && Boolean(initialConfig?.is_refreshing));
  const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(null);
  const lastCompletedAt = useRef(initialConfig?.last_refresh_at);
  const lastCounter = useRef(initialConfig?.refresh_counter);

  const reconcile = useCallback((next: Pick<AppConfig, 'last_refresh_at' | 'refresh_counter'>, complete = false) => {
    const previousStamp = lastCompletedAt.current;
    const previousCounter = lastCounter.current;
    const stamp = next.last_refresh_at;
    if (next.refresh_counter !== undefined) lastCounter.current = next.refresh_counter;
    if (stamp !== undefined) lastCompletedAt.current = stamp;

    if (stamp) {
      if (previousStamp && Date.parse(stamp) <= Date.parse(previousStamp)) {
        lastCompletedAt.current = previousStamp;
        return;
      }
      if (previousStamp !== undefined || complete) void refreshPortfolioData();
    } else if (complete || (previousCounter !== undefined && next.refresh_counter !== undefined && next.refresh_counter > previousCounter)) {
      void refreshPortfolioData();
    }
  }, [refreshPortfolioData]);

  const applyStreamEvent = useCallback((event: RefreshStreamEvent) => {
    if (event.type === 'connected') {
      setIsRefreshing(Boolean(event.is_refreshing));
      if (!event.is_refreshing) setBatchProgress(null);
      reconcile(event);
    } else if (event.type === 'complete' || event.type === 'error') {
      setIsRefreshing(false);
      setBatchProgress(null);
      if (event.type === 'complete') reconcile(event, true);
    } else if (event.type === 'start' || event.type === 'batch') {
      setIsRefreshing(true);
      setBatchProgress(readProgress(event));
      const quotes = event.quotes;
      if (!quotes) return;
      setPositions((positions) => applyBatchQuotesDelta(positions, quotes));
    }
  }, [reconcile, setPositions]);

  useEffect(() => {
    if (!enabled) return;
    const connect = () => startRefreshSync({
      openStream: (signal) => authFetch('/api/refresh/stream?mode=listen', {
        headers: { Accept: 'text/event-stream' }, cache: 'no-store', signal,
      }),
      getConfig,
      onEvent: applyStreamEvent,
      onConfig: (snapshot) => {
        setConfig(snapshot);
        setIsRefreshing(Boolean(snapshot.is_refreshing));
        setBatchProgress(snapshot.is_refreshing ? readProgress({ ...snapshot, batch_index: snapshot.current_batch }) : null);
        if (!snapshot.is_refreshing) reconcile(snapshot);
      },
    });
    let stop = connect();
    const pause = () => stop();
    const resume = (event: PageTransitionEvent) => {
      if (event.persisted) stop = connect();
    };
    window.addEventListener('pagehide', pause);
    window.addEventListener('pageshow', resume);
    return () => {
      stop();
      window.removeEventListener('pagehide', pause);
      window.removeEventListener('pageshow', resume);
    };
  }, [enabled, applyStreamEvent, reconcile]);

  const canTriggerRefresh = useEffectEvent(() => !isRefreshing);
  useEffect(() => {
    if (!enabled) return;
    const interval = 150_000;
    let lastAttemptAt = Date.now();
    let timer: ReturnType<typeof setInterval> | undefined;

    const trigger = () => {
      if (document.visibilityState !== 'visible' || !canTriggerRefresh()) return;
      lastAttemptAt = Date.now();
      void refreshAll().catch(() => {});
    };
    const syncVisibility = () => {
      clearInterval(timer);
      if (document.visibilityState !== 'visible') return;
      if (Date.now() - lastAttemptAt >= interval) trigger();
      timer = setInterval(trigger, interval);
    };

    syncVisibility();
    document.addEventListener('visibilitychange', syncVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', syncVisibility);
    };
  }, [enabled]);

  const value = useMemo(() => ({ config, isRefreshing, batchProgress, applyStreamEvent }), [config, isRefreshing, batchProgress, applyStreamEvent]);
  return <PortfolioRefreshContext value={value}>{children}</PortfolioRefreshContext>;
}

export function usePortfolioRefreshOptional(): PortfolioRefresh | null {
  return use(PortfolioRefreshContext);
}
