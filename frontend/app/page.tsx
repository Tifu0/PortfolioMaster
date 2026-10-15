import React, { Suspense } from 'react';
import Link from 'next/link';
import { getPositions, getMetrics } from '@/lib/api';
import type { Position, PortfolioMetrics } from '@/lib/types';
import { WatchlistContent } from '@/components/WatchlistContent';
import { BarChart3, PlusCircle, Upload, AlertCircle } from 'lucide-react';

function WatchlistSkeleton() {
  return (
    <div className="flex flex-col gap-6 animate-pulse">
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
  let fetchError: string | null = null;

  try {
    const [posResult, metricsResult] = await Promise.allSettled([
      getPositions(),
      getMetrics(),
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
      <WatchlistContent initialPositions={positions} initialMetrics={metrics} />
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
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
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex gap-2 border-t border-zinc-900 overflow-x-auto">
          <button className="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 border-emerald-500 text-emerald-400 bg-emerald-500/[0.03]">
            <BarChart3 className="w-4 h-4" />
            Watchlist
          </button>
          <Link
            href="/?add=1"
            className="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition"
            title="Añadir nuevo instrumento manualmente"
          >
            <PlusCircle className="w-4 h-4" />
            Añadir Valor
          </Link>
          <Link
            href="/import"
            className="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition"
          >
            <Upload className="w-4 h-4" />
            Importar
          </Link>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        {/* Header section with page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">
              Lista de Seguimiento
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              Valores registrados, cotizaciones en tiempo real y variaciones calculadas en el servidor.
            </p>
          </div>
        </div>

        {/* Suspense streaming data loader */}
        <Suspense fallback={<WatchlistSkeleton />}>
          <WatchlistDataLoader />
        </Suspense>
      </main>
    </div>
  );
}
