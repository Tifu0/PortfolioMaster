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
import { getPositions, getMetrics, getConfig, refreshAll } from '@/lib/api';
import { supabase, getAuthToken } from '@/lib/supabase';
import { useAuth } from '@/context/AuthContext';

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
  useEffect(() => {
    positionsRef.current = positions;
  }, [positions]);

  const { session, isLoading: isAuthLoading, isAuthConfigured } = useAuth();
  const prevSessionUserIdRef = useRef<string | null | undefined>(undefined);

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

      // When auth is configured but user is not signed in, do not flood protected endpoints with 401s
      if (isAuthConfigured && !session && !isAuthLoading) {
        setPositions([]);
        setMetrics(null);
        if (!isSilent) setIsRefreshing(false);
        return;
      }

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
    [isAuthConfigured, isAuthLoading, session]
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

  // Synchronize portfolio data when auth session changes (login / logout)
  useEffect(() => {
    if (!isAuthConfigured || isAuthLoading) return;
    const currentUserId = session?.user?.id ?? null;

    if (prevSessionUserIdRef.current === undefined) {
      prevSessionUserIdRef.current = currentUserId;
      if (currentUserId) {
        queueMicrotask(() => {
          refreshPortfolioData({ silent: false });
        });
      }
      return;
    }

    if (prevSessionUserIdRef.current !== currentUserId) {
      prevSessionUserIdRef.current = currentUserId;
      if (currentUserId) {
        queueMicrotask(() => {
          refreshPortfolioData({ silent: false });
        });
      } else {
        queueMicrotask(() => {
          setPositions([]);
          setMetrics(null);
        });
      }
    }
  }, [session, isAuthLoading, isAuthConfigured, refreshPortfolioData]);

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
      } catch {
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
  // Subscribes to live batch updates (/api/refresh/stream?mode=listen) using a fetch-based stream reader.
  // Securely sends Supabase Bearer token in headers without exposing credentials in query strings.
  useEffect(() => {
    if (typeof window === 'undefined') return;

    let abortController: AbortController | null = null;
    let isCancelled = false;
    let reconnectTimer: NodeJS.Timeout | null = null;

    async function connectSSEStream() {
      if (isCancelled) return;
      try {
        const token = await getAuthToken();
        if (isAuthConfigured && !token) {
          // Do not attempt authenticated SSE connection without a session
          return;
        }
        const headers: Record<string, string> = {
          Accept: 'text/event-stream',
        };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }

        const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';
        const streamUrl = `${baseUrl.replace(/\/$/, '')}/api/refresh/stream?mode=listen`;

        abortController = new AbortController();
        const res = await fetch(streamUrl, {
          headers,
          signal: abortController.signal,
        });

        if (!res.ok || !res.body) {
          if (!isCancelled && !reconnectTimer) {
            reconnectTimer = setTimeout(() => {
              reconnectTimer = null;
              connectSSEStream();
            }, 5000);
          }
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (!isCancelled) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split('\n\n');
          buffer = blocks.pop() || '';

          for (const block of blocks) {
            for (const line of block.split('\n')) {
              const trimmed = line.trim();
              if (trimmed.startsWith('data: ')) {
                try {
                  const data = JSON.parse(trimmed.slice(6));
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
              }
            }
          }
        }
      } catch (err: unknown) {
        if (!isCancelled && (err as { name?: string })?.name !== 'AbortError' && !reconnectTimer) {
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connectSSEStream();
          }, 5000);
        }
      }
    }

    connectSSEStream();

    return () => {
      isCancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (abortController) abortController.abort();
    };
  }, [refreshPortfolioData, isAuthConfigured]);

  // Global unhandled promise rejection listener
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      console.error('[PortfolioMaster Unhandled Rejection]:', event.reason);
    };
    window.addEventListener('unhandledrejection', handleUnhandledRejection);
    return () => window.removeEventListener('unhandledrejection', handleUnhandledRejection);
  }, []);

  // Keep live refs for timer callbacks
  const lastRefreshTimestampRef = useRef<number>(0);
  const isRefreshingRef = useRef<boolean>(isRefreshing);

  useEffect(() => {
    isRefreshingRef.current = isRefreshing;
  }, [isRefreshing]);

  useEffect(() => {
    if (lastRefreshTimestampRef.current === 0) {
      lastRefreshTimestampRef.current = Date.now();
    }
  }, []);

  useEffect(() => {
    if (lastRefreshedAt) {
      lastRefreshTimestampRef.current = lastRefreshedAt.getTime();
    }
  }, [lastRefreshedAt]);

  // 1. Smart visibility-aware timer: 150 seconds (2.5 min) with pause on blur and instant catch-up
  useEffect(() => {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;

    const SMART_REFRESH_INTERVAL_MS = 150_000;
    let intervalId: NodeJS.Timeout | null = null;

    const triggerSmartRefresh = async () => {
      if (document.visibilityState !== 'visible' || isRefreshingRef.current) {
        return;
      }
      try {
        await refreshAll();
      } catch (err) {
        console.debug('Background smart refresh tick completed/throttled:', err);
      } finally {
        await refreshPortfolioData({ silent: true });
      }
    };

    const startTimer = () => {
      if (intervalId) clearInterval(intervalId);
      intervalId = setInterval(triggerSmartRefresh, SMART_REFRESH_INTERVAL_MS);
    };

    const stopTimer = () => {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        const elapsedMs = Date.now() - lastRefreshTimestampRef.current;
        if (elapsedMs >= SMART_REFRESH_INTERVAL_MS) {
          triggerSmartRefresh();
        }
        startTimer();
      } else {
        stopTimer();
      }
    };

    // Initialize timer only if tab is currently visible
    if (document.visibilityState === 'visible') {
      startTimer();
    }

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      stopTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refreshPortfolioData]);

  // 2. Supabase Realtime synchronization on public.market_quotes
  useEffect(() => {
    const client = supabase;
    if (!client) return;

    const channel = client
      .channel('realtime:market_quotes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'market_quotes' },
        () => {
          // Silent background revalidation without table layout shifts
          refreshPortfolioData({ silent: true });
        }
      )
      .subscribe();

    return () => {
      client.removeChannel(channel);
    };
  }, [refreshPortfolioData]);

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

export function usePortfolioOptional(): PortfolioContextType | null {
  return use(PortfolioContext);
}
