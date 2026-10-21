'use client';

import React, {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from 'react';
import { useRouter } from 'next/navigation';
import type { Position, PortfolioMetrics, AppConfig } from '@/lib/types';
import { getPositions, getMetrics, getConfig } from '@/lib/api';

export interface PortfolioContextType {
  positions: Position[];
  metrics: PortfolioMetrics | null;
  config: AppConfig | null;
  isRefreshing: boolean;
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

  const isInitialSeededRef = useRef(initialPositions.length > 0);
  const router = useRouter();
  const [, startTransition] = useTransition();

  // Seed initial data passed from server components or initial render
  const seedInitialData = useCallback(
    (
      newPositions: Position[],
      newMetrics: PortfolioMetrics | null,
      newConfig?: AppConfig | null
    ) => {
      if (!isInitialSeededRef.current) {
        setPositions(newPositions);
        if (newMetrics) setMetrics(newMetrics);
        if (newConfig) setConfig(newConfig);
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

        // Non-blocking Next.js server route refresh to sync RSC cache without UI interruption
        startTransition(() => {
          try {
            router.refresh();
          } catch {
            // Safe fallback if router is not mounted in test environments
          }
        });
      } catch (err) {
        console.error('Error during portfolio data refresh:', err);
      } finally {
        if (!isSilent) {
          setIsRefreshing(false);
        }
      }
    },
    [router]
  );

  // Optimistic UI: Immediately delete an instrument and return a rollback callback
  const optimisticDelete = useCallback(
    (ticker: string) => {
      const previousPositions = [...positions];
      const previousMetrics = metrics ? { ...metrics } : null;

      // 1. Immediately remove from local reactive state
      setPositions((prev) => prev.filter((p) => p.user_ticker !== ticker));

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
    [positions, metrics]
  );

  // Optimistic UI: Immediately update position fields (e.g. comments, targets)
  const optimisticUpdatePosition = useCallback(
    (ticker: string, updates: Partial<Position>) => {
      const previousPositions = [...positions];

      setPositions((prev) =>
        prev.map((item) => (item.user_ticker === ticker ? { ...item, ...updates } : item))
      );

      return () => {
        setPositions(previousPositions);
      };
    },
    [positions]
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

        // Initialize baselines on initial mount
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

        // Update tracking state
        lastKnownRefreshAtRef.current = cfg.last_refresh_at ?? null;
        lastKnownCounterRef.current = cfg.refresh_counter ?? 0;
        wasRefreshingRef.current = Boolean(cfg.is_refreshing);
        setConfig(cfg);

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
