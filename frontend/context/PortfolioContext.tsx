'use client';

import React, {
  createContext,
  use,
  useCallback,
  useEffect,
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

  // Fetch initial config on mount if not provided
  useEffect(() => {
    let active = true;
    if (!config) {
      getConfig()
        .then((cfg) => {
          if (active) setConfig(cfg);
        })
        .catch((err) => {
          console.warn('Could not load backend config:', err);
        });
    }
    return () => {
      active = false;
    };
  }, [config]);

  // Periodic background auto-refresh driven by config.refresh_interval_seconds
  useEffect(() => {
    const intervalSec = config?.refresh_interval_seconds;
    if (!intervalSec || intervalSec <= 0) return;

    const intervalMs = intervalSec * 1000;
    const intervalId = setInterval(() => {
      refreshPortfolioData({ silent: true });
    }, intervalMs);

    return () => clearInterval(intervalId);
  }, [config?.refresh_interval_seconds, refreshPortfolioData]);

  const value: PortfolioContextType = {
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
  };

  return <PortfolioContext value={value}>{children}</PortfolioContext>;
}

export function usePortfolio(): PortfolioContextType {
  const context = use(PortfolioContext);
  if (!context) {
    throw new Error('usePortfolio must be used within a PortfolioProvider');
  }
  return context;
}
