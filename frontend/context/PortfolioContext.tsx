'use client';

import { createContext, use, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { getMetrics, getPositions } from '@/lib/api';
import type { AppConfig, PortfolioMetrics, Position } from '@/lib/types';
import { useAuth } from './AuthContext';
import { PortfolioRefreshProvider } from './PortfolioRefreshContext';

interface PortfolioData {
  positions: Position[];
  metrics: PortfolioMetrics | null;
  isInitialized: boolean;
  refreshPortfolioData: (options?: { silent?: boolean }) => Promise<void>;
  optimisticDelete: (ticker: string) => () => void;
  optimisticUpdatePosition: (ticker: string, updates: Partial<Position>) => () => void;
  setPositions: Dispatch<SetStateAction<Position[]>>;
  setMetrics: Dispatch<SetStateAction<PortfolioMetrics | null>>;
}

const PortfolioDataContext = createContext<PortfolioData | null>(null);

interface PortfolioProviderProps {
  children: ReactNode;
  initialPositions: Position[];
  initialMetrics: PortfolioMetrics | null;
  initialConfig: AppConfig | null;
  initialDataReady: boolean;
  serverUserId: string | null;
}

export function PortfolioProvider({ serverUserId, ...props }: PortfolioProviderProps) {
  const { user, isAuthConfigured } = useAuth();
  const enabled = !isAuthConfigured || Boolean(user && user.id === serverUserId);
  // A cookie identity change must discard the previous tenant's state and stream.
  const identity = enabled ? serverUserId ?? 'local' : 'signed-out';
  return <PortfolioDataProvider key={identity} {...props} enabled={enabled} />;
}

function PortfolioDataProvider({
  children, initialPositions, initialMetrics, initialConfig, initialDataReady, enabled,
}: Omit<PortfolioProviderProps, 'serverUserId'> & { enabled: boolean }) {
  const [positions, setPositions] = useState<Position[]>(enabled ? initialPositions : []);
  const [metrics, setMetrics] = useState(enabled ? initialMetrics : null);
  const [isInitialized, setIsInitialized] = useState(!enabled || initialDataReady);
  const active = useRef(true);
  const inFlight = useRef<Promise<void> | null>(null);
  const queued = useRef(false);

  const refreshPortfolioData = useCallback((): Promise<void> => {
    if (!enabled || !active.current) return Promise.resolve();
    if (inFlight.current) {
      queued.current = true;
      return inFlight.current;
    }

    async function load() {
      do {
        queued.current = false;
        const [positionsResult, metricsResult] = await Promise.allSettled([getPositions(), getMetrics()]);
        if (!active.current) return;
        if (positionsResult.status === 'fulfilled') setPositions(positionsResult.value.positions ?? []);
        if (metricsResult.status === 'fulfilled') setMetrics(metricsResult.value);
        setIsInitialized(true);
      } while (queued.current);
    }

    inFlight.current = load().finally(() => { inFlight.current = null; });
    return inFlight.current;
  }, [enabled]);

  useEffect(() => {
    active.current = true;
    if (!initialDataReady && !inFlight.current) void refreshPortfolioData();
    return () => { active.current = false; };
  }, [initialDataReady, refreshPortfolioData]);

  const optimisticDelete = useCallback((ticker: string) => {
    const index = positions.findIndex((position) => position.user_ticker === ticker);
    const previous = positions[index];
    if (!previous) return () => {};

    setPositions((current) => current.filter((position) => position.user_ticker !== ticker));
    return () => setPositions((current) => current.some((position) => position.user_ticker === ticker)
      ? current
      : [...current.slice(0, index), previous, ...current.slice(index)]);
  }, [positions]);

  const optimisticUpdatePosition = useCallback((ticker: string, updates: Partial<Position>) => {
    const previous = positions.find((position) => position.user_ticker === ticker);
    if (!previous) return () => {};

    const updated = { ...previous, ...updates };
    setPositions((current) => current.map((position) => position === previous ? updated : position));
    return () => setPositions((current) => current.map((position) => position === updated ? previous : position));
  }, [positions]);

  const value = useMemo(() => ({
    positions, metrics, isInitialized, refreshPortfolioData, optimisticDelete, optimisticUpdatePosition,
    setPositions, setMetrics,
  }), [positions, metrics, isInitialized, refreshPortfolioData, optimisticDelete, optimisticUpdatePosition]);

  return (
    <PortfolioDataContext value={value}>
      <PortfolioRefreshProvider
        enabled={enabled}
        initialConfig={initialConfig}
        refreshPortfolioData={refreshPortfolioData}
        setPositions={setPositions}
      >
        {children}
      </PortfolioRefreshProvider>
    </PortfolioDataContext>
  );
}

export function usePortfolioDataOptional(): PortfolioData | null {
  return use(PortfolioDataContext);
}

export function usePortfolioData(): PortfolioData {
  const context = usePortfolioDataOptional();
  if (!context) throw new Error('usePortfolioData requires a PortfolioProvider');
  return context;
}
