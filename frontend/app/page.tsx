import React, { Suspense } from 'react';
import Link from 'next/link';
import { getPositions, getMetrics, getConfig } from '@/lib/api';
import type { Position, PortfolioMetrics, AppConfig } from '@/lib/types';
import { WatchlistContent } from '@/components/WatchlistContent';
import { HeaderNav } from '@/components/HeaderNav';
import { BarChart3, AlertCircle } from 'lucide-react';

function WatchlistSkeleton() {
  return (
    <div className="flex flex-col gap-6 animate-pulse">
      {/* Header section skeleton */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="h-7 w-56 bg-zinc-800 rounded-lg mb-2" />
          <div className="h-4 w-96 max-w-full bg-zinc-800/60 rounded" />
        </div>
        <div className="h-8 w-36 bg-zinc-800/60 rounded-full self-start sm:self-auto" />
      </div>

      {/* 4 Skeleton Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-32 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-5 flex flex-col justify-between"
          >
            <div className="flex items-center justify-between">
              <div className="h-3 w-24 bg-zinc-800 rounded" />
              <div className="w-8 h-8 rounded-lg bg-zinc-800" />
            </div>
            <div className="h-8 w-20 bg-zinc-800 rounded" />
            <div className="h-3 w-full bg-zinc-800/60 rounded" />
          </div>
        ))}
      </div>

      {/* Table Skeletons */}
      <div className="flex flex-col gap-4">
        <div className="h-14 bg-zinc-900/80 border border-zinc-800 rounded-xl w-full" />
        <div className="h-96 bg-zinc-900/40 border border-zinc-800 rounded-xl w-full flex items-center justify-center">
          <span className="text-xs font-mono text-zinc-500">Cargando cotizaciones y métricas...</span>
        </div>
      </div>
    </div>
  );
}

async function WatchlistDataLoader() {
  let positions: Position[] = [];
  let metrics: PortfolioMetrics | null = null;
  let config: AppConfig | null = null;
  let fetchError: string | null = null;

  try {
    const [posResult, metricsResult, configResult] = await Promise.allSettled([
      getPositions(),
      getMetrics(),
      getConfig(),
    ]);

    if (posResult.status === 'fulfilled') {
      positions = posResult.value.positions || [];
    } else {
      const err = posResult.reason;
      fetchError = err instanceof Error ? err.message : String(err);
    }

    if (metricsResult.status === 'fulfilled') {
      metrics = metricsResult.value;
    }

    if (configResult.status === 'fulfilled') {
      config = configResult.value;
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    fetchError = msg;
    positions = [];
  }

  return (
    <div className="flex flex-col gap-6">
      {fetchError && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs flex items-center gap-3">
          <AlertCircle className="w-4 h-4 shrink-0 text-amber-400" />
          <span>
            Aviso de conexión: No se pudo conectar con el backend FastAPI ({fetchError}).
            Asegúrate de que el servidor está corriendo en <code className="bg-amber-500/20 px-1 py-0.5 rounded font-mono">http://localhost:8000</code>.
          </span>
        </div>
      )}

      {/* Phase 6: WatchlistContent wraps MetricCards + WatchlistTable with shared reactive state */}
      <WatchlistContent
        initialPositions={positions}
        initialMetrics={metrics}
        initialConfig={config}
      />
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <BarChart3 className="w-5 h-5" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight text-white flex items-center gap-2">
                PortfolioMaster
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700/60 font-normal">
                  v1.0
                </span>
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-zinc-400 font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              FastAPI :8000
            </span>
          </div>
        </div>

        {/* Tab Navigation */}
        <HeaderNav />
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-[1680px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        {/* Suspense streaming data loader */}
        <Suspense fallback={<WatchlistSkeleton />}>
          <WatchlistDataLoader />
        </Suspense>
      </main>
    </div>
  );
}
