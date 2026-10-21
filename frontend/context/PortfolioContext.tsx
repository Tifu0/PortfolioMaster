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
  isInitialized: boolean;
  lastRefreshedAt: Date | null;
  refreshPortfolioData: (options?: { silent?: boolean }) => Promise<void>;
  optimisticDelete: (ticker: string) => () => void;
  optimisticUpdatePosition: (ticker: string, updates: Partial<Position>) => () => void;
  setPositions: React.Dispatch<React.SetStateAction<Position[]>>;
  setMetrics: React.Dispatch<React.SetStateAction<PortfolioMetrics | null>>;
  setConfig: React.Dispatch<React.SetStateAction<AppConfig | null>>;
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

  // Active sync heartbeat: polls /api/config every 3 seconds to detect when
  // background batch updates complete in the backend, triggering zero-F5 silent updates.
  useEffect(() => {
    let isCancelled = false;

    async function checkBackendSync() {
      if (isSyncingRef.current) return;
      isSyncingRef.current = true;
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
      }
    }

    // Initial check immediately on mount
    checkBackendSync();

    // 3-second heartbeat to detect backend batch finishes with near-zero latency
    const intervalId = setInterval(checkBackendSync, 3000);

    return () => {
      isCancelled = true;
      clearInterval(intervalId);
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
      isInitialized,
      lastRefreshedAt,
      refreshPortfolioData,
      optimisticDelete,
      optimisticUpdatePosition,
      setPositions,
      setMetrics,
      setConfig,
      seedInitialData,
    }),
    [
      positions,
      metrics,
      config,
      isRefreshing,
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
