'use client';

import React, {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { Position, PortfolioMetrics, AppConfig } from '@/lib/types';
import { getPositions, getMetrics, getConfig } from '@/lib/api';

export interface PortfolioContextType {
  positions: Position[];
  metrics: PortfolioMetrics | null;
  config: AppConfig | null;
  isRefreshing: boolean;
  batchProgress: { currentBatch: number; totalBatches: number; processed: number; total: number } | null;
  isInitialized: boolean;
  lastRefreshedAt: Date | null;
  refreshPortfolioData: (options?: { silent?: boolean }) => Promise<void>;
  optimisticDelete: (ticker: string) => () => void;
  optimisticUpdatePosition: (ticker: string, updates: Partial<Position>) => () => void;
  setPositions: React.Dispatch<React.SetStateAction<Position[]>>;
  setMetrics: React.Dispatch<React.SetStateAction<PortfolioMetrics | null>>;
  setConfig: React.Dispatch<React.SetStateAction<AppConfig | null>>;
  setBatchProgress: React.Dispatch<
    React.SetStateAction<{ currentBatch: number; totalBatches: number; processed: number; total: number } | null>
  >;
  seedInitialData: (
    positions: Position[],
    metrics: PortfolioMetrics | null,
    config?: AppConfig | null
  ) => void;
}

const PortfolioContext = createContext<PortfolioContextType | null>(null);

export interface PortfolioProviderProps {
  children: React.ReactNode;
  initialPositions?: Position[];
  initialMetrics?: PortfolioMetrics | null;
  initialConfig?: AppConfig | null;
}

export function PortfolioProvider({
  children,
  initialPositions = [],
  initialMetrics = null,
  initialConfig = null,
}: PortfolioProviderProps) {
  const [positions, setPositions] = useState<Position[]>(initialPositions);
  const [metrics, setMetrics] = useState<PortfolioMetrics | null>(initialMetrics);
  const [config, setConfig] = useState<AppConfig | null>(initialConfig);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{
    currentBatch: number;
    totalBatches: number;
    processed: number;
    total: number;
  } | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [isInitialized, setIsInitialized] = useState(initialPositions.length > 0);

  const isInitialSeededRef = useRef(initialPositions.length > 0);
  const positionsRef = useRef(positions);
  positionsRef.current = positions;

  // Seed initial data passed from server components or initial render
  const seedInitialData = useCallback(
    (
      newPositions: Position[],
      newMetrics: PortfolioMetrics | null,
      newConfig?: AppConfig | null
    ) => {
      if (!isInitialSeededRef.current || positionsRef.current.length === 0) {
        setPositions(newPositions);
        if (newMetrics) setMetrics(newMetrics);
        if (newConfig) setConfig(newConfig);
        setIsInitialized(true);
        isInitialSeededRef.current = true;
      }
    },
    []
  );

  // Centralized silent refresh mechanism ("Zero-F5" Architecture)
  const refreshPortfolioData = useCallback(
    async (options?: { silent?: boolean }) => {
      const isSilent = options?.silent ?? false;
      if (!isSilent) {
        setIsRefreshing(true);
      }

      try {
        const [posRes, metRes, cfgRes] = await Promise.allSettled([
          getPositions(),
          getMetrics(),
          getConfig(),
        ]);

        let updatedPositions: Position[] | null = null;
        let updatedMetrics: PortfolioMetrics | null = null;
        let updatedConfig: AppConfig | null = null;

        if (posRes.status === 'fulfilled') {
          updatedPositions = posRes.value.positions || [];
          setPositions(updatedPositions);
          setIsInitialized(true);
        }

        if (metRes.status === 'fulfilled') {
          updatedMetrics = metRes.value;
          setMetrics(updatedMetrics);
        }

        if (cfgRes.status === 'fulfilled') {
          updatedConfig = cfgRes.value;
          setConfig(updatedConfig);
        }

        setLastRefreshedAt(new Date());
      } catch (err) {
        console.error('Error during portfolio data refresh:', err);
      } finally {
        if (!isSilent) {
          setIsRefreshing(false);
        }
      }
    },
    []
  );

  // Optimistic UI: Immediately delete an instrument and return a rollback callback
  const optimisticDelete = useCallback(
    (ticker: string) => {
      let previousPositions: Position[] = [];
      let previousMetrics: PortfolioMetrics | null = null;

      // 1. Immediately remove from local reactive state
      setPositions((prev) => {
        previousPositions = prev;
        return prev.filter((p) => p.user_ticker !== ticker);
      });

      setMetrics((prev) => {
        previousMetrics = prev;
        return prev;
      });

      // 2. Trigger a silent background recalculation of metrics
      getMetrics()
        .then((freshMetrics) => setMetrics(freshMetrics))
        .catch(() => {});

      // 3. Return rollback function to execute if server deletion fails
      return () => {
        setPositions(previousPositions);
        if (previousMetrics) setMetrics(previousMetrics);
      };
    },
    []
  );

  // Optimistic UI: Immediately update position fields (e.g. comments, targets)
  const optimisticUpdatePosition = useCallback(
    (ticker: string, updates: Partial<Position>) => {
      let previousPositions: Position[] = [];

      setPositions((prev) => {
        previousPositions = prev;
        return prev.map((item) => (item.user_ticker === ticker ? { ...item, ...updates } : item));
      });

      return () => {
        setPositions(previousPositions);
      };
    },
    []
  );

  const lastKnownRefreshAtRef = useRef<string | null | undefined>(undefined);
  const lastKnownCounterRef = useRef<number | undefined>(undefined);
  const wasRefreshingRef = useRef<boolean>(false);
  const isSyncingRef = useRef<boolean>(false);

  // Active sync heartbeat: checks /api/config on mount and adaptively polls
  // (fast 2s polling only when backend is actively refreshing; quiet 30s when idle)
  // to detect when background batch updates complete in the backend, triggering zero-F5 silent updates.
  useEffect(() => {
    let isCancelled = false;
    let timerId: NodeJS.Timeout | null = null;

    async function checkBackendSync() {
      if (isSyncingRef.current || isCancelled) return;
      isSyncingRef.current = true;
      let nextIntervalMs = 30000; // Idle quiet interval: 30s instead of 3s spam
      try {
        const cfg = await getConfig();
        if (isCancelled) return;

        const prevRefreshAt = lastKnownRefreshAtRef.current;
        const prevCounter = lastKnownCounterRef.current;
        const wasRefreshing = wasRefreshingRef.current;

        // Initialize baselines on initial mount without redundant state churn
        if (prevRefreshAt === undefined && prevCounter === undefined) {
          lastKnownRefreshAtRef.current = cfg.last_refresh_at ?? null;
          lastKnownCounterRef.current = cfg.refresh_counter ?? 0;
          wasRefreshingRef.current = Boolean(cfg.is_refreshing);
          setConfig(cfg);
          if (cfg.is_refreshing) {
            nextIntervalMs = 2000;
          }
          return;
        }

        const counterChanged =
          cfg.refresh_counter !== undefined &&
          prevCounter !== undefined &&
          cfg.refresh_counter > prevCounter;

        const refreshAtChanged =
          Boolean(cfg.last_refresh_at) &&
          prevRefreshAt !== undefined &&
          cfg.last_refresh_at !== prevRefreshAt;

        const finishedRefreshing = wasRefreshing && !cfg.is_refreshing;
        const isRefreshingChanged = wasRefreshing !== Boolean(cfg.is_refreshing);

        // Update tracking state
        lastKnownRefreshAtRef.current = cfg.last_refresh_at ?? null;
        lastKnownCounterRef.current = cfg.refresh_counter ?? 0;
        wasRefreshingRef.current = Boolean(cfg.is_refreshing);

        // Adaptive polling: only poll every 2s while refresh is actively in progress
        if (cfg.is_refreshing) {
          nextIntervalMs = 2000;
        }

        // Only update config state if it actually changed to prevent re-render churn!
        if (counterChanged || refreshAtChanged || finishedRefreshing || isRefreshingChanged) {
          setConfig(cfg);
        }

        // If a batch finished in the backend, trigger silent portfolio reload immediately!
        if (counterChanged || refreshAtChanged || finishedRefreshing) {
          await refreshPortfolioData({ silent: true });
        }
      } catch (err) {
        // Silently ignore transient network blips
      } finally {
        isSyncingRef.current = false;
        if (!isCancelled) {
          timerId = setTimeout(checkBackendSync, nextIntervalMs);
        }
      }
    }

    // Initial check immediately on mount
    checkBackendSync();

    return () => {
      isCancelled = true;
      if (timerId) clearTimeout(timerId);
    };
  }, [refreshPortfolioData]);

  // Real-Time Server-Sent Events (SSE) Listener:
  // Subscribes to live batch updates (/api/refresh/stream?mode=listen) so both automatic scheduled refreshes
  // and manual batch refreshes update positions and progress live batch-by-batch across the app.
  useEffect(() => {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') return;

    let eventSource: EventSource | null = null;
    let isCancelled = false;
    let reconnectTimer: NodeJS.Timeout | null = null;

    function connectSSE() {
      if (isCancelled) return;
      try {
        const streamUrl = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/refresh/stream?mode=listen`;
        eventSource = new EventSource(streamUrl);

        eventSource.onmessage = (event) => {
          if (isCancelled || !event.data) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'start') {
              setIsRefreshing(true);
              if (data.total_batches) {
                setBatchProgress({
                  currentBatch: 0,
                  totalBatches: data.total_batches,
                  processed: 0,
                  total: data.total_symbols ?? 0,
                });
              }
            } else if (data.type === 'batch') {
              setIsRefreshing(true);
              if (data.batch_index && data.total_batches) {
                setBatchProgress({
                  currentBatch: data.batch_index,
                  totalBatches: data.total_batches,
                  processed: data.processed_symbols ?? 0,
                  total: data.total_symbols ?? 0,
                });
              }
              // Progressive live update: re-fetch positions & metrics in background per completed batch
              refreshPortfolioData({ silent: true });
            } else if (data.type === 'complete') {
              setBatchProgress(null);
              setIsRefreshing(false);
              refreshPortfolioData({ silent: true });
            } else if (data.type === 'error') {
              setBatchProgress(null);
              setIsRefreshing(false);
            }
          } catch {
            // Ignore non-json or comments
          }
        };

        eventSource.onerror = () => {
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }
          if (!isCancelled && !reconnectTimer) {
            reconnectTimer = setTimeout(() => {
              reconnectTimer = null;
              connectSSE();
            }, 5000);
          }
        };
      } catch {
        // SSE connection failure handled silently, fallback to checkBackendSync
      }
    }

    connectSSE();

    return () => {
      isCancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (eventSource) eventSource.close();
    };
  }, [refreshPortfolioData]);

  // Fallback periodic auto-refresh driven by config.refresh_interval_seconds
  useEffect(() => {
    const intervalSec = config?.refresh_interval_seconds;
    if (!intervalSec || intervalSec <= 0) return;

    const intervalMs = intervalSec * 1000;
    const intervalId = setInterval(() => {
      refreshPortfolioData({ silent: true });
    }, intervalMs);

    return () => clearInterval(intervalId);
  }, [config?.refresh_interval_seconds, refreshPortfolioData]);

  const value = useMemo<PortfolioContextType>(
    () => ({
      positions,
      metrics,
      config,
      isRefreshing,
      batchProgress,
      isInitialized,
      lastRefreshedAt,
      refreshPortfolioData,
      optimisticDelete,
      optimisticUpdatePosition,
      setPositions,
      setMetrics,
      setConfig,
      setBatchProgress,
      seedInitialData,
    }),
    [
      positions,
      metrics,
      config,
      isRefreshing,
      batchProgress,
      isInitialized,
      lastRefreshedAt,
      refreshPortfolioData,
      optimisticDelete,
      optimisticUpdatePosition,
      seedInitialData,
    ]
  );

  return <PortfolioContext value={value}>{children}</PortfolioContext>;
}

export function usePortfolio(): PortfolioContextType {
  const context = use(PortfolioContext);
  if (!context) {
    throw new Error('usePortfolio must be used within a PortfolioProvider');
  }
  return context;
}
