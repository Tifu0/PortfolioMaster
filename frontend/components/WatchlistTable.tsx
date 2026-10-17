'use client';

// 'use client' is required here because sorting, global text filtering,
// exchange/currency dropdown filters, refresh actions, and wipe database
// modal all require interactive React state (useState, useMemo, useCallback)
// and TanStack Table client-side hooks.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ColumnDef,
  ColumnSizingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from '@tanstack/react-table';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Search,
  Filter,
  TrendingDown,
  TrendingUp,
  Info,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
  AlertTriangle,
  Check,
  Loader2,
  Edit3,
  PlusCircle,
  Calendar,
  FileText,
} from 'lucide-react';
import type { Position, QuoteStatus, PortfolioMetrics, RefreshBatchResponse, AppConfig } from '@/lib/types';
import {
  getPositions,
  getMetrics,
  refreshAll,
  refreshInstrument,
  resolveMissingAnalysisPrices,
  updateInstrument,
  wipeDatabase,
} from '@/lib/api';

// ========================================================================== //
// Props
// ========================================================================== //

interface WatchlistTableProps {
  initialPositions: Position[];
  initialMetrics?: PortfolioMetrics | null;
  appConfig?: AppConfig | null;
  onDataChange?: (positions: Position[], metrics: PortfolioMetrics | null) => void;
  onEditTicker?: (ticker: string) => void;
  onAddInstrument?: () => void;
}

// ========================================================================== //
// Helpers
// ========================================================================== //

function formatPercent(value: number | null | undefined, valid: boolean): { text: string; colorClass: string } {
  if (!valid || value === null || value === undefined || isNaN(value)) {
    return { text: 'N/A', colorClass: 'text-zinc-500 font-mono text-xs' };
  }
  const formatted = `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  if (value > 0.0001) {
    return { text: formatted, colorClass: 'text-emerald-400 font-semibold font-mono' };
  } else if (value < -0.0001) {
    return { text: formatted, colorClass: 'text-rose-400 font-semibold font-mono' };
  }
  return { text: formatted, colorClass: 'text-zinc-300 font-mono' };
}

function formatDeclineToTarget(
  value: number | null | undefined,
  valid: boolean
): { text: string; colorClass: string } {
  // Para empresas que no tengan precio objetivo (o cálculo no válido),
  // se asigna por predeterminado un -100% de caída (mínima intensidad roja)
  const effectiveValue =
    !valid || value === null || value === undefined || isNaN(value)
      ? -100
      : value;

  const formatted = `${effectiveValue >= 0 ? '+' : ''}${effectiveValue.toFixed(2)}%`;

  // Si ya ha alcanzado o superado el objetivo (caída restante <= 0%)
  if (effectiveValue >= 0) {
    return {
      text: formatted,
      colorClass:
        'text-emerald-300 font-bold font-mono text-xs px-2 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-500/40 shadow-sm shadow-emerald-950/40',
    };
  }

  // Cuanto más cerca del objetivo (menor % de caída restante), más intenso es el rojo:
  // El recuadro / badge se aplica a partir de -10% hacia delante (hacia 0%):
  const absVal = Math.abs(effectiveValue);

  if (absVal <= 2) {
    // Alerta inminente (≤ 2%, ej. 1%): Máxima intensidad roja con recuadro pulsante
    return {
      text: formatted,
      colorClass:
        'text-rose-100 font-bold font-mono text-xs px-2 py-0.5 rounded-md bg-rose-600/40 border border-rose-500/60 shadow-md shadow-rose-950/60 animate-pulse',
    };
  }
  if (absVal <= 5) {
    // Muy cerca (2% a 5%): Rojo intenso con recuadro destacado
    return {
      text: formatted,
      colorClass:
        'text-rose-200 font-bold font-mono text-xs px-1.5 py-0.5 rounded bg-rose-500/25 border border-rose-500/40',
    };
  }
  if (absVal <= 10) {
    // De -10% hacia delante: Rojo vivo con recuadro suave
    return {
      text: formatted,
      colorClass:
        'text-rose-300 font-semibold font-mono text-xs px-1.5 py-0.5 rounded bg-rose-500/15 border border-rose-500/25',
    };
  }
  // A partir de más de -10% de caída (más lejos), SIN recuadro:
  if (absVal <= 30) {
    // Distancia media (10% a 30%): Rojo estándar sin recuadro
    return {
      text: formatted,
      colorClass: 'text-rose-400 font-medium font-mono text-xs',
    };
  }
  if (absVal <= 50) {
    // Distancia moderada (30% a 50%): Rojo moderado sin recuadro
    return {
      text: formatted,
      colorClass: 'text-rose-400/80 font-normal font-mono text-xs',
    };
  }
  if (absVal <= 75) {
    // Distancia lejana (50% a 75%, ej. 70%): Rojo leve sin recuadro
    return {
      text: formatted,
      colorClass: 'text-rose-400/50 font-normal font-mono text-xs',
    };
  }
  // Distancia muy lejana (75% a 100%+ o sin objetivo, ej. -100%): Mínima intensidad roja sin recuadro
  return {
    text: formatted,
    colorClass: 'text-rose-400/30 font-normal font-mono text-xs',
  };
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

function timeAgo(isoDate: string | null | undefined): string {
  if (!isoDate) return '';
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return '';
    const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
    if (seconds < 60) return 'hace unos segundos';
    if (seconds < 3600) return `hace ${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)}h`;
    return `hace ${Math.floor(seconds / 86400)}d`;
  } catch {
    return '';
  }
}

// ========================================================================== //
// QuoteStatusBadge — Enhanced with pulse, provider, and timestamp
// ========================================================================== //

function QuoteStatusBadge({
  status,
  provider,
  fetchedAt,
}: {
  status: QuoteStatus | string | null;
  provider?: string | null;
  fetchedAt?: string | null;
}) {
  if (!status) return null;
  const s = String(status).toUpperCase();

  const badges: Record<string, { label: string; classes: string; title: string; pulse?: boolean }> = {
    FRESH: {
      label: 'Live',
      classes: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
      title: 'Cotización en tiempo real',
      pulse: true,
    },
    DELAYED: {
      label: 'Cerrado',
      classes: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
      title: 'Cierre de mercado / diferido 15min',
    },
    STALE: {
      label: 'Vencido',
      classes: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
      title: 'Datos desactualizados — supera el umbral de frescura',
    },
    UNAVAILABLE: {
      label: 'No disponible',
      classes: 'bg-zinc-600/10 text-zinc-400 border-zinc-600/20',
      title: 'Sin cotización disponible para este instrumento',
    },
    ERROR: {
      label: 'Error',
      classes: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
      title: 'Error al obtener la cotización',
    },
  };

  const cfg = badges[s];
  if (!cfg) return null;

  const provStr = provider ? String(provider) : null;
  const elapsed = timeAgo(fetchedAt);
  const tooltipParts = [cfg.title];
  if (provStr) tooltipParts.push(`Proveedor: ${provStr}`);
  if (elapsed) tooltipParts.push(elapsed);

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border ${cfg.classes}`}
        title={tooltipParts.join(' · ')}
      >
        {cfg.pulse && (
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
          </span>
        )}
        {cfg.label}
      </span>
      {provStr && (
        <span className="px-1 py-0.5 rounded text-[9px] font-mono bg-zinc-800/60 text-zinc-500 border border-zinc-700/40">
          {provStr}
        </span>
      )}
    </span>
  );
}

// ========================================================================== //
// Toast Notification
// ========================================================================== //

interface ToastData {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

function Toast({ toast, onDismiss }: { toast: ToastData; onDismiss: () => void }) {
  const colors = {
    success: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300',
    error: 'bg-rose-500/10 border-rose-500/20 text-rose-300',
    info: 'bg-blue-500/10 border-blue-500/20 text-blue-300',
  };
  const icons = {
    success: <Check className="w-4 h-4 text-emerald-400 shrink-0" />,
    error: <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />,
    info: <Info className="w-4 h-4 text-blue-400 shrink-0" />,
  };

  React.useEffect(() => {
    const timer = setTimeout(onDismiss, 5000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-xs shadow-lg backdrop-blur animate-in slide-in-from-top-2 ${colors[toast.type]}`}
    >
      {icons[toast.type]}
      <span className="flex-1">{toast.message}</span>
      <button onClick={onDismiss} className="hover:opacity-70 transition-opacity">
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

// ========================================================================== //
// Wipe Database Confirmation Modal
// ========================================================================== //

function WipeDatabaseModal({
  open,
  onClose,
  onConfirm,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  loading: boolean;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl p-6 animate-in zoom-in-95">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-5 h-5 text-rose-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white">
              Borrar Base de Datos
            </h3>
            <p className="mt-2 text-sm text-zinc-400 leading-relaxed">
              Esta acción eliminará <strong className="text-zinc-200">todos los instrumentos y cotizaciones</strong> de
              la base de datos. Esta acción no se puede deshacer.
            </p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium text-zinc-300 bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition-colors disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-rose-600 hover:bg-rose-500 border border-rose-500 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Borrando...
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4" />
                Sí, borrar todo
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ========================================================================== //
// Main Component
// ========================================================================== //

export function WatchlistTable({
  initialPositions,
  initialMetrics: _initialMetrics,
  appConfig,
  onDataChange,
  onEditTicker,
  onAddInstrument,
}: WatchlistTableProps) {
  const [data, setData] = useState<Position[]>(initialPositions);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState('');
  const [selectedExchange, setSelectedExchange] = useState<string>('ALL');
  const [selectedCurrency, setSelectedCurrency] = useState<string>('ALL');

  // Column sizing states
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({});

  useEffect(() => {
    try {
      const saved = localStorage.getItem('portfoliomaster_column_sizing');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && typeof parsed === 'object') {
          setColumnSizing(parsed);
        }
      }
    } catch {
      // ignore storage access errors
    }
  }, []);

  const handleColumnSizingChange = useCallback(
    (updater: React.SetStateAction<ColumnSizingState>) => {
      setColumnSizing((prev) => {
        const next = typeof updater === 'function' ? updater(prev) : updater;
        try {
          localStorage.setItem('portfoliomaster_column_sizing', JSON.stringify(next));
        } catch {
          // ignore
        }
        return next;
      });
    },
    []
  );

  const hasCustomColumnSizing = useMemo(
    () => Object.keys(columnSizing).length > 0,
    [columnSizing]
  );

  // Refresh states
  const [batchRefreshing, setBatchRefreshing] = useState(false);
  const [resolvingAnalysisPrices, setResolvingAnalysisPrices] = useState(false);
  const [refreshingTickers, setRefreshingTickers] = useState<Set<string>>(new Set());

  // Wipe database modal
  const [wipeModalOpen, setWipeModalOpen] = useState(false);
  const [wipingDb, setWipingDb] = useState(false);

  // Toasts
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const toastIdRef = React.useRef(0);

  const addToast = useCallback((type: ToastData['type'], message: string) => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, type, message }]);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const handleResetColumnWidths = useCallback(() => {
    setColumnSizing({});
    try {
      localStorage.removeItem('portfoliomaster_column_sizing');
    } catch {
      // ignore
    }
    addToast('info', 'Ancho de columnas restablecido a los valores por defecto');
  }, [addToast]);

  // Description / Notes states
  const [expandedDescriptionTickers, setExpandedDescriptionTickers] = useState<Set<string>>(new Set());
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [savingCommentTicker, setSavingCommentTicker] = useState<string | null>(null);

  const toggleDescription = useCallback((ticker: string) => {
    setExpandedDescriptionTickers((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) {
        next.delete(ticker);
      } else {
        next.add(ticker);
        setCommentDrafts((drafts) => {
          if (drafts[ticker] === undefined) {
            const currentPos = data.find((p) => p.user_ticker === ticker);
            return { ...drafts, [ticker]: currentPos?.comment || '' };
          }
          return drafts;
        });
      }
      return next;
    });
  }, [data]);

  const handleCommentChange = useCallback((ticker: string, value: string) => {
    setCommentDrafts((prev) => ({ ...prev, [ticker]: value }));
  }, []);

  const handleSaveComment = useCallback(async (pos: Position) => {
    const ticker = pos.user_ticker;
    const newComment = commentDrafts[ticker] !== undefined ? commentDrafts[ticker] : (pos.comment || '');
    setSavingCommentTicker(ticker);
    try {
      await updateInstrument(ticker, { comment: newComment });
      setData((prev) => {
        const updated = prev.map((item) =>
          item.user_ticker === ticker ? { ...item, comment: newComment } : item
        );
        onDataChange?.(updated, _initialMetrics ?? null);
        return updated;
      });
      addToast('success', `Descripción de ${ticker} guardada correctamente`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Error al guardar la descripción de ${ticker}: ${msg}`);
    } finally {
      setSavingCommentTicker(null);
    }
  }, [commentDrafts, addToast, onDataChange, _initialMetrics]);

  // ── Reload data from API ────────────────────────────────────────────── //

  const reloadData = useCallback(async () => {
    try {
      const [posResult, metricsResult] = await Promise.allSettled([
        getPositions(),
        getMetrics(),
      ]);

      let newPositions: Position[] = [];
      let newMetrics: PortfolioMetrics | null = null;

      if (posResult.status === 'fulfilled') {
        newPositions = posResult.value.positions || [];
      }
      if (metricsResult.status === 'fulfilled') {
        newMetrics = metricsResult.value;
      }

      setData(newPositions);
      onDataChange?.(newPositions, newMetrics);
    } catch {
      // Silently handle — the toast from the caller is sufficient
    }
  }, [onDataChange]);

  // ── Batch Refresh (Cotizaciones + Precios de Análisis) ───────────────── //

  const handleBatchRefresh = useCallback(async () => {
    if (batchRefreshing) return;
    setBatchRefreshing(true);
    try {
      const [quotesRes, analysisRes] = await Promise.allSettled([
        refreshAll(),
        resolveMissingAnalysisPrices(),
      ]);

      let updatedQuotes = 0;
      let totalQuotes = 0;
      let failedQuotes = 0;
      if (quotesRes.status === 'fulfilled') {
        updatedQuotes = quotesRes.value.updated;
        totalQuotes = quotesRes.value.total;
        failedQuotes = quotesRes.value.failed;
      }

      let updatedAnalysis = 0;
      if (analysisRes.status === 'fulfilled') {
        updatedAnalysis = analysisRes.value.updated;
      }

      const failedMsg = failedQuotes > 0 ? ` (${failedQuotes} fallidas)` : '';
      const analysisMsg = updatedAnalysis > 0 ? ` · ${updatedAnalysis} precios de análisis resueltos` : '';
      addToast(
        failedQuotes > 0 ? 'info' : 'success',
        `${updatedQuotes} de ${totalQuotes} cotizaciones actualizadas${failedMsg}${analysisMsg}`
      );
      await reloadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Error al actualizar cotizaciones: ${msg}`);
    } finally {
      setBatchRefreshing(false);
    }
  }, [batchRefreshing, addToast, reloadData]);

  // ── Single Row Refresh ──────────────────────────────────────────────── //

  const handleSingleRefresh = useCallback(
    async (ticker: string) => {
      if (refreshingTickers.has(ticker)) return;
      setRefreshingTickers((prev) => new Set(prev).add(ticker));
      try {
        const result = await refreshInstrument(ticker);
        if (result.status === 'ok') {
          addToast('success', `${ticker}: cotización actualizada`);
        } else {
          addToast('info', `${ticker}: ${result.detail || 'sin cotización'}`);
        }
        await reloadData();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        addToast('error', `Error al actualizar ${ticker}: ${msg}`);
      } finally {
        setRefreshingTickers((prev) => {
          const next = new Set(prev);
          next.delete(ticker);
          return next;
        });
      }
    },
    [refreshingTickers, addToast, reloadData]
  );

  // ── Wipe Database ───────────────────────────────────────────────────── //

  const handleWipeDatabase = useCallback(async () => {
    setWipingDb(true);
    try {
      await wipeDatabase();
      addToast('success', 'Base de datos borrada correctamente.');
      setData([]);
      onDataChange?.([], null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Error al borrar la base de datos: ${msg}`);
    } finally {
      setWipingDb(false);
      setWipeModalOpen(false);
    }
  }, [addToast, onDataChange]);

  // ── Resolve Missing Analysis Prices ────────────────────────────────── //

  const handleResolveAnalysisPrices = useCallback(async () => {
    if (resolvingAnalysisPrices) return;
    setResolvingAnalysisPrices(true);
    try {
      const res = await resolveMissingAnalysisPrices();
      addToast(
        'success',
        `Precios de fecha de análisis: ${res.updated} actualizados (${res.failed} no encontrados, ${res.skipped} ya tenían precio)`
      );
      await reloadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Error al resolver precios de análisis: ${msg}`);
    } finally {
      setResolvingAnalysisPrices(false);
    }
  }, [resolvingAnalysisPrices, addToast, reloadData]);

  // ── Computed filters ────────────────────────────────────────────────── //

  const exchanges = useMemo(() => {
    const set = new Set<string>();
    data.forEach((p) => {
      if (p.exchange) set.add(p.exchange);
    });
    return Array.from(set).sort();
  }, [data]);

  const currencies = useMemo(() => {
    const set = new Set<string>();
    data.forEach((p) => {
      if (p.currency) set.add(p.currency);
    });
    return Array.from(set).sort();
  }, [data]);

  const filteredData = useMemo(() => {
    return data.filter((row) => {
      if (selectedExchange !== 'ALL' && row.exchange !== selectedExchange) return false;
      if (selectedCurrency !== 'ALL' && row.currency !== selectedCurrency) return false;
      if (globalFilter.trim()) {
        const query = globalFilter.toLowerCase();
        const tickerMatch = row.user_ticker.toLowerCase().includes(query);
        const nameMatch = row.company_name.toLowerCase().includes(query);
        const symbolMatch = row.provider_symbol?.toLowerCase().includes(query);
        if (!tickerMatch && !nameMatch && !symbolMatch) return false;
      }
      return true;
    });
  }, [data, selectedExchange, selectedCurrency, globalFilter]);

  // ── Column definitions ──────────────────────────────────────────────── //

  const columns = useMemo<ColumnDef<Position>[]>(
    () => [
      {
        accessorKey: 'user_ticker',
        size: 130,
        minSize: 85,
        maxSize: 350,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            Ticker
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => {
          const pos = row.original;
          const isTargetReached =
            pos.target_price !== null &&
            pos.latest_price !== null &&
            pos.target_price > 0 &&
            pos.latest_price > 0 &&
            pos.latest_price <= pos.target_price;

          if (isTargetReached) {
            return (
              <div
                className="inline-flex flex-col px-2.5 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-400/50 shadow-[0_0_12px_rgba(16,185,129,0.35)] transition-all"
                title={`¡Precio objetivo alcanzado! Cotización (${pos.latest_price} ${pos.currency}) ≤ Objetivo (${pos.target_price} ${pos.currency})`}
              >
                <div className="flex items-center gap-1.5">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
                  </span>
                  <span className="font-bold text-emerald-200 tracking-wide font-mono text-xs">
                    {pos.user_ticker}
                  </span>
                </div>
                {pos.provider_symbol && pos.provider_symbol !== pos.user_ticker && (
                  <span className="text-[10px] text-emerald-400/80 font-mono pl-3.5">
                    {pos.provider_symbol}
                  </span>
                )}
              </div>
            );
          }

          return (
            <div className="flex flex-col">
              <span className="font-semibold text-white tracking-wide font-mono">
                {pos.user_ticker}
              </span>
              {pos.provider_symbol && pos.provider_symbol !== pos.user_ticker && (
                <span className="text-[11px] text-zinc-500 font-mono">
                  {pos.provider_symbol}
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: 'company_name',
        size: 240,
        minSize: 130,
        maxSize: 600,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            Empresa
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => (
          <span className="text-zinc-200 font-medium truncate max-w-[200px] block" title={row.original.company_name}>
            {row.original.company_name || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'exchange',
        size: 105,
        minSize: 80,
        maxSize: 220,
        header: 'Mercado',
        cell: ({ row }) => (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono bg-zinc-800 text-zinc-300 border border-zinc-700/60">
            {row.original.exchange || 'AUTO'}
          </span>
        ),
      },
      {
        accessorKey: 'currency',
        size: 85,
        minSize: 65,
        maxSize: 160,
        header: 'Divisa',
        cell: ({ row }) => (
          <span className="text-xs font-mono text-zinc-400">
            {row.original.currency || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'latest_price',
        size: 160,
        minSize: 110,
        maxSize: 320,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 justify-end w-full hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            Último Precio
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => {
          const pos = row.original;
          return (
            <div className="flex flex-col items-end gap-1">
              <span className="font-mono font-medium text-white">
                {formatCurrency(pos.latest_price, pos.currency)}
              </span>
              <QuoteStatusBadge
                status={pos.quote_status}
                provider={pos.quote_provider}
                fetchedAt={pos.quote_fetched_at}
              />
            </div>
          );
        },
      },
      {
        accessorKey: 'daily_variation',
        size: 130,
        minSize: 95,
        maxSize: 260,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 justify-end w-full hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            Var. Diaria
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => {
          const { text, colorClass } = formatPercent(
            row.original.daily_variation,
            row.original.daily_variation_valid
          );
          return (
            <div className="flex items-center justify-end gap-1">
              {row.original.daily_variation_valid && row.original.daily_variation !== null && (
                row.original.daily_variation >= 0 ? (
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
                )
              )}
              <span className={colorClass}>{text}</span>
            </div>
          );
        },
      },
      {
        accessorKey: 'variation_since_analysis',
        size: 150,
        minSize: 110,
        maxSize: 320,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 justify-end w-full hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            Var. vs Análisis
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => {
          const pos = row.original;
          const { text, colorClass } = formatPercent(
            pos.variation_since_analysis,
            pos.variation_since_analysis_valid
          );
          return (
            <div className="flex flex-col items-end">
              <span className={colorClass}>{text}</span>
              {pos.analysis_reference_price !== null && pos.analysis_reference_price !== undefined ? (
                <span className="text-[10px] text-zinc-500 font-mono">
                  {formatCurrency(pos.analysis_reference_price, pos.currency)}
                  {pos.analysis_date ? ` (${pos.analysis_date})` : ''}
                </span>
              ) : pos.analysis_date ? (
                <button
                  type="button"
                  onClick={() => onEditTicker?.(pos.user_ticker)}
                  className="text-[10px] text-amber-500/80 hover:text-amber-400 font-mono underline decoration-dotted transition-colors"
                  title={`Fecha: ${pos.analysis_date}. Haz clic para asignar precio o consultar Yahoo.`}
                >
                  {pos.analysis_date} (sin ref)
                </button>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorFn: (row) =>
          row.decline_to_target_valid && row.decline_to_target !== null
            ? row.decline_to_target
            : -100,
        id: 'decline_to_target',
        size: 150,
        minSize: 110,
        maxSize: 320,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 justify-end w-full hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            Caída a Objetivo
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => {
          const { text, colorClass } = formatDeclineToTarget(
            row.original.decline_to_target,
            row.original.decline_to_target_valid
          );
          return (
            <div className="flex items-center justify-end">
              <span className={colorClass}>{text}</span>
            </div>
          );
        },
      },
      {
        accessorKey: 'target_price',
        size: 130,
        minSize: 95,
        maxSize: 260,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1.5 justify-end w-full hover:text-white transition-colors uppercase text-xs tracking-wider"
          >
            P. Objetivo
            {column.getIsSorted() === 'asc' ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-400" />
            ) : column.getIsSorted() === 'desc' ? (
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />
            )}
          </button>
        ),
        cell: ({ row }) => (
          <div className="flex justify-end font-mono text-zinc-300">
            {formatCurrency(row.original.target_price, row.original.currency)}
          </div>
        ),
      },
      // Actions column — per-row description, edit & refresh
      {
        id: 'actions',
        size: 115,
        minSize: 115,
        maxSize: 115,
        enableResizing: false,
        header: '',
        cell: ({ row }) => {
          const ticker = row.original.user_ticker;
          const isRefreshing = refreshingTickers.has(ticker);
          const isExpanded = expandedDescriptionTickers.has(ticker);
          const hasComment = Boolean(row.original.comment && row.original.comment.trim());

          return (
            <div className="flex items-center justify-end gap-1">
              {/* Description toggle button */}
              <button
                onClick={() => toggleDescription(ticker)}
                className={`p-1.5 rounded-lg transition-all relative ${
                  isExpanded
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                    : hasComment
                    ? 'text-blue-400 hover:text-blue-300 hover:bg-blue-500/10'
                    : 'text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800'
                }`}
                title={
                  hasComment
                    ? `Descripción: "${row.original.comment.slice(0, 60)}${row.original.comment.length > 60 ? '...' : ''}" (clic para ${isExpanded ? 'ocultar' : 'desplegar'})`
                    : `Añadir descripción para ${ticker}`
                }
              >
                <FileText className="w-3.5 h-3.5" />
                {hasComment && (
                  <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-blue-400" />
                )}
              </button>

              {/* Edit instrument modal button */}
              <button
                onClick={() => onEditTicker?.(ticker)}
                className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 transition-all"
                title={`Modificar datos de ${ticker}`}
              >
                <Edit3 className="w-3.5 h-3.5" />
              </button>

              {/* Refresh quote button */}
              <button
                onClick={() => handleSingleRefresh(ticker)}
                disabled={isRefreshing || batchRefreshing}
                className="p-1.5 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-emerald-400 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                title={`Actualizar cotización de ${ticker}`}
              >
                {isRefreshing ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                ) : (
                  <RefreshCw className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          );
        },
      },
    ],
    [
      refreshingTickers,
      batchRefreshing,
      handleSingleRefresh,
      onEditTicker,
      expandedDescriptionTickers,
      toggleDescription,
    ]
  );

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: filteredData,
    columns,
    state: {
      sorting,
      columnSizing,
    },
    onSortingChange: setSorting,
    onColumnSizingChange: handleColumnSizingChange,
    columnResizeMode: 'onChange',
    enableColumnResizing: true,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <div className="flex flex-col gap-4 relative">
      {/* Toast Layer */}
      {toasts.length > 0 && (
        <div className="fixed top-20 right-4 z-[200] flex flex-col gap-2 max-w-sm w-full pointer-events-auto">
          {toasts.map((t) => (
            <Toast key={t.id} toast={t} onDismiss={() => dismissToast(t.id)} />
          ))}
        </div>
      )}

      {/* Wipe Database Modal */}
      <WipeDatabaseModal
        open={wipeModalOpen}
        onClose={() => setWipeModalOpen(false)}
        onConfirm={handleWipeDatabase}
        loading={wipingDb}
      />

      {/* Search, Filters & Action Buttons Bar */}
      <div className="flex flex-col xl:flex-row items-stretch xl:items-center justify-between gap-3 bg-zinc-900/80 backdrop-blur border border-zinc-800 p-2.5 sm:p-3 rounded-xl">
        {/* Left side: Search & Filter Controls */}
        <div className="flex flex-wrap sm:flex-nowrap items-center gap-2 flex-1 min-w-0">
          {/* Search Input */}
          <div className="relative min-w-[160px] sm:min-w-[200px] max-w-xs flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
            <input
              type="text"
              placeholder="Buscar ticker o empresa..."
              value={globalFilter}
              onChange={(e) => setGlobalFilter(e.target.value)}
              className="w-full bg-zinc-950/70 border border-zinc-800 rounded-lg pl-9 pr-3 py-1.5 text-xs sm:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 transition-all font-sans h-9"
            />
          </div>

          {/* Mercado Filter */}
          <div className="flex items-center gap-1.5 bg-zinc-950/50 border border-zinc-800 rounded-lg px-2.5 h-9 shrink-0">
            <Filter className="w-3.5 h-3.5 text-zinc-400" />
            <span className="text-xs text-zinc-400">Mercado:</span>
            <select
              value={selectedExchange}
              onChange={(e) => setSelectedExchange(e.target.value)}
              className="bg-transparent text-xs text-zinc-200 font-medium focus:outline-none cursor-pointer pr-1"
            >
              <option value="ALL" className="bg-zinc-900 text-zinc-200">Todos</option>
              {exchanges.map((ex) => (
                <option key={ex} value={ex} className="bg-zinc-900 text-zinc-200">
                  {ex}
                </option>
              ))}
            </select>
          </div>

          {/* Divisa Filter */}
          <div className="flex items-center gap-1.5 bg-zinc-950/50 border border-zinc-800 rounded-lg px-2.5 h-9 shrink-0">
            <span className="text-xs text-zinc-400">Divisa:</span>
            <select
              value={selectedCurrency}
              onChange={(e) => setSelectedCurrency(e.target.value)}
              className="bg-transparent text-xs text-zinc-200 font-medium focus:outline-none cursor-pointer pr-1"
            >
              <option value="ALL" className="bg-zinc-900 text-zinc-200">Todas</option>
              {currencies.map((curr) => (
                <option key={curr} value={curr} className="bg-zinc-900 text-zinc-200">
                  {curr}
                </option>
              ))}
            </select>
          </div>

          {/* Counter Badge */}
          <div className="inline-flex items-center text-xs text-zinc-400 px-2.5 h-9 font-mono whitespace-nowrap shrink-0 bg-zinc-950/40 border border-zinc-800/80 rounded-lg">
            Mostrando <span className="text-zinc-200 font-semibold mx-1">{filteredData.length}</span> de{' '}
            <span className="text-zinc-200 font-semibold ml-1">{data.length}</span>
          </div>
        </div>

        {/* Right side: Action Buttons */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap sm:flex-nowrap">
          {/* Add Instrument Button */}
          {onAddInstrument && (
            <button
              onClick={onAddInstrument}
              className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
                bg-zinc-800/90 text-zinc-200 border border-zinc-700
                hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
              title="Añadir un nuevo valor manualmente"
            >
              <PlusCircle className="w-4 h-4 text-emerald-400" />
              <span className="hidden sm:inline">Añadir Valor</span>
            </button>
          )}

          {/* Batch Refresh (Cotizaciones + Precios de Análisis) */}
          <button
            onClick={handleBatchRefresh}
            disabled={batchRefreshing || data.length === 0}
            className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
              bg-emerald-500/10 text-emerald-400 border border-emerald-500/20
              hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/40
              disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            title="Actualizar todas las cotizaciones y precios de análisis desde Yahoo Finance"
          >
            {batchRefreshing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="hidden sm:inline">Actualizando...</span>
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                <span className="hidden sm:inline">Actualizar Cotizaciones</span>
              </>
            )}
          </button>

          {/* Reset Column Widths Button */}
          <button
            onClick={handleResetColumnWidths}
            disabled={!hasCustomColumnSizing}
            className={`h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all shrink-0 border ${
              hasCustomColumnSizing
                ? 'bg-zinc-800 text-zinc-200 border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm cursor-pointer'
                : 'bg-zinc-900/40 text-zinc-600 border-zinc-800/60 cursor-not-allowed opacity-50'
            }`}
            title={
              hasCustomColumnSizing
                ? 'Restablecer el ancho de las columnas a los valores por defecto'
                : 'Las columnas ya tienen su ancho por defecto'
            }
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span className="hidden xl:inline">Restablecer Columnas</span>
          </button>

          {/* Wipe Database */}
          <button
            onClick={() => setWipeModalOpen(true)}
            disabled={batchRefreshing || wipingDb}
            className="h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all
              bg-rose-500/5 text-zinc-500 border border-zinc-800
              hover:bg-rose-500/10 hover:text-rose-400 hover:border-rose-500/30
              disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
            title="Borrar todos los datos de la base de datos"
          >
            <Trash2 className="w-4 h-4" />
            <span className="hidden sm:inline">Borrar BD</span>
          </button>
        </div>
      </div>

      {/* Table Container */}
      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900/40 backdrop-blur shadow-2xl">
        <table
          className="w-full text-left text-sm text-zinc-300 divide-y divide-zinc-800/80 table-fixed"
          style={{ width: `${table.getTotalSize()}px`, minWidth: '100%' }}
        >
          <thead className="bg-zinc-950/70 text-xs text-zinc-400">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    scope="col"
                    style={{ width: `${header.getSize()}px` }}
                    className="py-3.5 px-4 font-semibold text-zinc-400 relative select-none group/th"
                  >
                    <div className="truncate">
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </div>

                    {/* Column Resizer Handle */}
                    {header.column.getCanResize() && (
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        onDoubleClick={() => header.column.resetSize()}
                        onClick={(e) => e.stopPropagation()}
                        className={`absolute right-0 top-0 h-full w-2.5 cursor-col-resize select-none touch-none flex items-center justify-center transition-all group-hover/th:opacity-100 z-20 ${
                          header.column.getIsResizing()
                            ? 'opacity-100'
                            : 'opacity-0'
                        }`}
                        title="Arrastra para redimensionar (doble clic para valor por defecto)"
                      >
                        <div
                          className={`w-[2px] transition-all rounded-full ${
                            header.column.getIsResizing()
                              ? 'bg-emerald-400 h-full shadow-[0_0_8px_rgba(52,211,153,0.9)]'
                              : 'bg-zinc-600 hover:bg-emerald-400 h-4'
                          }`}
                        />
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-zinc-800/60 font-sans">
            {table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => {
                const ticker = row.original.user_ticker;
                const isRefreshingRow = refreshingTickers.has(ticker);
                const isExpanded = expandedDescriptionTickers.has(ticker);
                const currentComment =
                  commentDrafts[ticker] !== undefined
                    ? commentDrafts[ticker]
                    : row.original.comment || '';
                const hasUnsavedChanges =
                  currentComment !== (row.original.comment || '');

                return (
                  <React.Fragment key={row.id}>
                    <tr
                      className={`hover:bg-zinc-800/30 transition-colors group ${
                        isRefreshingRow ? 'opacity-60' : ''
                      } ${isExpanded ? 'bg-zinc-850/60' : ''}`}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td
                          key={cell.id}
                          style={{ width: `${cell.column.getSize()}px` }}
                          className="py-3.5 px-4 align-middle overflow-hidden"
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </td>
                      ))}
                    </tr>
                    {isExpanded && (
                      <tr className="bg-zinc-900/95 border-b border-zinc-800">
                        <td
                          colSpan={row.getVisibleCells().length}
                          className="px-4 py-3.5 sm:px-6"
                        >
                          <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4 space-y-3 shadow-lg animate-in fade-in-50 duration-150">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2.5">
                                <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                                  <FileText className="w-4 h-4" />
                                </div>
                                <div>
                                  <span className="text-xs font-semibold text-white">
                                    Descripción de la Empresa
                                  </span>
                                  <span className="text-xs text-zinc-400 ml-2 font-mono">
                                    {row.original.user_ticker} · {row.original.company_name}
                                  </span>
                                </div>
                              </div>
                              <button
                                onClick={() => toggleDescription(ticker)}
                                className="text-zinc-500 hover:text-zinc-300 p-1 rounded-lg hover:bg-zinc-800 transition"
                                title="Cerrar panel de descripción"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            </div>

                            <textarea
                              value={currentComment}
                              onChange={(e) =>
                                handleCommentChange(ticker, e.target.value)
                              }
                              placeholder={`Escribe aquí la descripción, notas o tesis de inversión de ${row.original.company_name}...`}
                              rows={3}
                              className="w-full bg-zinc-900/90 border border-zinc-800 rounded-lg p-3 text-xs sm:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all font-sans leading-relaxed resize-y"
                            />

                            <div className="flex items-center justify-between text-xs pt-0.5">
                              <span className="text-zinc-500 text-[11px] font-mono">
                                {currentComment.length} caracteres
                                {hasUnsavedChanges && (
                                  <span className="ml-2 text-amber-400">
                                    • Cambios sin guardar
                                  </span>
                                )}
                              </span>
                              <div className="flex items-center gap-2">
                                <button
                                  onClick={() => toggleDescription(ticker)}
                                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
                                >
                                  Cerrar
                                </button>
                                <button
                                  onClick={() => handleSaveComment(row.original)}
                                  disabled={savingCommentTicker === ticker}
                                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
                                >
                                  {savingCommentTicker === ticker ? (
                                    <>
                                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                      Guardando...
                                    </>
                                  ) : (
                                    <>
                                      <Check className="w-3.5 h-3.5" />
                                      Guardar Descripción
                                    </>
                                  )}
                                </button>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            ) : (
              <tr>
                <td
                  colSpan={columns.length}
                  className="py-16 text-center text-zinc-400"
                >
                  <div className="flex flex-col items-center justify-center gap-2.5 max-w-sm mx-auto">
                    <Info className="w-8 h-8 text-zinc-600" />
                    <p className="text-sm font-medium text-zinc-300">
                      {data.length === 0
                        ? 'La lista de seguimiento está vacía.'
                        : 'No se encontraron valores con los filtros actuales.'}
                    </p>
                    <p className="text-xs text-zinc-500">
                      {data.length === 0
                        ? 'Añade valores manualmente o importa un archivo CSV/Excel.'
                        : 'Prueba a cambiar los criterios de búsqueda o el filtro de mercado/divisa.'}
                    </p>
                    {data.length === 0 && onAddInstrument && (
                      <button
                        onClick={onAddInstrument}
                        className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-950/40"
                      >
                        <PlusCircle className="w-4 h-4" />
                        Añadir Primer Valor
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )}

            {/* Permanent Bottom Row: Añadir un nuevo valor */}
            {onAddInstrument && (
              <tr
                onClick={onAddInstrument}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onAddInstrument();
                  }
                }}
                tabIndex={0}
                role="button"
                className="group cursor-pointer border-t-2 border-dashed border-zinc-800/80 bg-zinc-950/30 hover:bg-emerald-500/[0.07] hover:border-emerald-500/30 transition-all select-none focus:outline-none focus:bg-emerald-500/[0.09]"
                title="Añadir un nuevo valor manualmente al watchlist"
              >
                <td
                  colSpan={columns.length}
                  className="py-3 px-4 text-left"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center group-hover:bg-emerald-500/20 group-hover:border-emerald-500/40 group-hover:scale-105 transition-all text-emerald-400 shrink-0">
                      <PlusCircle className="w-3.5 h-3.5" />
                    </span>
                    <span className="text-xs font-semibold text-emerald-400 group-hover:text-emerald-300 transition-colors">
                      Añadir un nuevo valor
                    </span>
                    <span className="hidden sm:inline text-[11px] text-zinc-500 group-hover:text-zinc-400 transition-colors">
                      — Haz clic aquí para registrar un instrumento o cotización manualmente
                    </span>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Batch refresh overlay — subtle full-table indicator */}
      {batchRefreshing && (
        <div className="absolute inset-0 bg-zinc-950/20 rounded-xl flex items-center justify-center pointer-events-none z-10">
          <div className="flex items-center gap-3 bg-zinc-900/95 border border-zinc-700 rounded-xl px-5 py-3 shadow-2xl">
            <Loader2 className="w-5 h-5 animate-spin text-emerald-400" />
            <span className="text-sm text-zinc-200 font-medium">Actualizando Yahoo Finance...</span>
          </div>
        </div>
      )}
    </div>
  );
}
