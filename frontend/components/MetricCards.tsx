import React from 'react';
import {
  Layers,
  TrendingUp,
  TrendingDown,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from 'lucide-react';
import type { PortfolioMetrics, Position } from '@/lib/types';

interface MetricCardsProps {
  metrics?: PortfolioMetrics | null;
  positions?: Position[];
}

function formatCurrency(price: number | null | undefined, currency: string): string {
  if (price === null || price === undefined || isNaN(price)) {
    return '—';
  }
  const curr = currency ? currency.toUpperCase() : 'EUR';
  try {
    return new Intl.NumberFormat('es-ES', {
      style: 'currency',
      currency: curr.length === 3 ? curr : 'EUR',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(price);
  } catch {
    return `${price.toFixed(2)} ${currency}`;
  }
}

/**
 * MetricCards: Server Component presenting high-level portfolio KPIs:
 * 1. Total Positions & Active Quotes
 * 2. Best Performer of the Day (Top Gainer)
 * 3. Worst Performer of the Day (Top Loser)
 * 4. Average Daily Variation & Market Sentiment
 */
export function MetricCards({ metrics: providedMetrics, positions }: MetricCardsProps) {
  // If backend metrics are provided, use them. Otherwise, compute fallback from positions array.
  const metrics: PortfolioMetrics = React.useMemo(() => {
    if (providedMetrics) {
      return providedMetrics;
    }

    const posList = positions || [];
    const total = posList.length;
    const valid = posList.filter(
      (p) => p.daily_variation_valid && p.daily_variation !== null && !isNaN(p.daily_variation)
    );

    if (valid.length === 0) {
      return {
        total_positions: total,
        positions_with_quotes: 0,
        best_performer: null,
        worst_performer: null,
        average_daily_change: null,
        positive_count: 0,
        negative_count: 0,
        neutral_count: 0,
      };
    }

    const sorted = [...valid].sort(
      (a, b) => (a.daily_variation ?? 0) - (b.daily_variation ?? 0)
    );
    const worst = sorted[0];
    const best = sorted[sorted.length - 1];

    const sum = valid.reduce((acc, p) => acc + (p.daily_variation ?? 0), 0);
    const avg = Math.round((sum / valid.length) * 100) / 100;

    return {
      total_positions: total,
      positions_with_quotes: valid.length,
      best_performer: best
        ? {
            user_ticker: best.user_ticker,
            company_name: best.company_name,
            daily_variation: best.daily_variation ?? 0,
            latest_price: best.latest_price,
            currency: best.currency,
          }
        : null,
      worst_performer: worst
        ? {
            user_ticker: worst.user_ticker,
            company_name: worst.company_name,
            daily_variation: worst.daily_variation ?? 0,
            latest_price: worst.latest_price,
            currency: worst.currency,
          }
        : null,
      average_daily_change: avg,
      positive_count: valid.filter((p) => (p.daily_variation ?? 0) > 0.0001).length,
      negative_count: valid.filter((p) => (p.daily_variation ?? 0) < -0.0001).length,
      neutral_count: valid.filter(
        (p) => Math.abs(p.daily_variation ?? 0) <= 0.0001
      ).length,
    };
  }, [providedMetrics, positions]);

  const avgChange = metrics.average_daily_change;
  const avgColorClass =
    avgChange === null
      ? 'text-zinc-400'
      : avgChange > 0
      ? 'text-emerald-400'
      : avgChange < 0
      ? 'text-rose-400'
      : 'text-zinc-200';

  return (
    <section aria-label="Métricas del Portfolio" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* 1. Total Positions */}
      <div className="relative group overflow-hidden rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-5 backdrop-blur transition-all duration-200 hover:border-zinc-700 hover:bg-zinc-900/90 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-zinc-400 tracking-wide uppercase">
            Total Posiciones
          </span>
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
            <Layers className="w-4 h-4" />
          </div>
        </div>

        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
            {metrics.total_positions}
          </span>
          <span className="text-xs text-zinc-400 font-medium">valores</span>
        </div>

        <div className="mt-2.5 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/60 pt-2.5">
          <span className="flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                metrics.positions_with_quotes > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'
              }`}
            />
            {metrics.positions_with_quotes} con cotización
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-300">
            Activos
          </span>
        </div>
      </div>

      {/* 2. Best Performer */}
      <div className="relative group overflow-hidden rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-5 backdrop-blur transition-all duration-200 hover:border-emerald-500/30 hover:bg-zinc-900/90 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-zinc-400 tracking-wide uppercase">
            Mayor Subida
          </span>
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
            <TrendingUp className="w-4 h-4" />
          </div>
        </div>

        {metrics.best_performer ? (
          <>
            <div className="mt-3 flex items-baseline justify-between gap-2">
              <span className="text-2xl font-bold tracking-tight text-white font-mono truncate" title={metrics.best_performer.user_ticker}>
                {metrics.best_performer.user_ticker}
              </span>
              <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-semibold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <ArrowUpRight className="w-3.5 h-3.5" />
                +{metrics.best_performer.daily_variation.toFixed(2)}%
              </span>
            </div>

            <div className="mt-2.5 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/60 pt-2.5">
              <span className="truncate max-w-[140px]" title={metrics.best_performer.company_name}>
                {metrics.best_performer.company_name}
              </span>
              <span className="font-mono text-zinc-300 font-medium shrink-0">
                {formatCurrency(metrics.best_performer.latest_price, metrics.best_performer.currency)}
              </span>
            </div>
          </>
        ) : (
          <div className="mt-4 flex flex-col justify-center text-xs text-zinc-500 py-2">
            <span className="font-mono text-lg text-zinc-600">—</span>
            <span className="mt-1">Sin cotizaciones disponibles</span>
          </div>
        )}
      </div>

      {/* 3. Worst Performer */}
      <div className="relative group overflow-hidden rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-5 backdrop-blur transition-all duration-200 hover:border-rose-500/30 hover:bg-zinc-900/90 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-zinc-400 tracking-wide uppercase">
            Mayor Caída
          </span>
          <div className="w-8 h-8 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
            <TrendingDown className="w-4 h-4" />
          </div>
        </div>

        {metrics.worst_performer ? (
          <>
            <div className="mt-3 flex items-baseline justify-between gap-2">
              <span className="text-2xl font-bold tracking-tight text-white font-mono truncate" title={metrics.worst_performer.user_ticker}>
                {metrics.worst_performer.user_ticker}
              </span>
              <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-semibold font-mono bg-rose-500/10 text-rose-400 border border-rose-500/20">
                <ArrowDownRight className="w-3.5 h-3.5" />
                {metrics.worst_performer.daily_variation.toFixed(2)}%
              </span>
            </div>

            <div className="mt-2.5 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/60 pt-2.5">
              <span className="truncate max-w-[140px]" title={metrics.worst_performer.company_name}>
                {metrics.worst_performer.company_name}
              </span>
              <span className="font-mono text-zinc-300 font-medium shrink-0">
                {formatCurrency(metrics.worst_performer.latest_price, metrics.worst_performer.currency)}
              </span>
            </div>
          </>
        ) : (
          <div className="mt-4 flex flex-col justify-center text-xs text-zinc-500 py-2">
            <span className="font-mono text-lg text-zinc-600">—</span>
            <span className="mt-1">Sin cotizaciones disponibles</span>
          </div>
        )}
      </div>

      {/* 4. Average Daily Return & Market Balance */}
      <div className="relative group overflow-hidden rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-5 backdrop-blur transition-all duration-200 hover:border-zinc-700 hover:bg-zinc-900/90 shadow-sm">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-zinc-400 tracking-wide uppercase">
            Var. Media Diaria
          </span>
          <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <Activity className="w-4 h-4" />
          </div>
        </div>

        <div className="mt-3 flex items-baseline gap-2">
          <span className={`text-3xl font-extrabold tracking-tight font-mono ${avgColorClass}`}>
            {avgChange !== null ? `${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%` : '—'}
          </span>
          <span className="text-xs text-zinc-400 font-medium">media</span>
        </div>

        <div className="mt-2.5 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/60 pt-2.5">
          <div className="flex items-center gap-1.5 font-mono text-[11px]">
            <span className="text-emerald-400 flex items-center">
              ▲ {metrics.positive_count}
            </span>
            <span className="text-zinc-600">|</span>
            <span className="text-rose-400 flex items-center">
              ▼ {metrics.negative_count}
            </span>
            {metrics.neutral_count > 0 && (
              <>
                <span className="text-zinc-600">|</span>
                <span className="text-zinc-400 flex items-center">
                  <Minus className="w-2.5 h-2.5 mr-0.5" /> {metrics.neutral_count}
                </span>
              </>
            )}
          </div>
          <span className="text-[10px] text-zinc-400">
            {metrics.positions_with_quotes} activos
          </span>
        </div>
      </div>
    </section>
  );
}
