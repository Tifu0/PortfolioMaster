'use client';

// 'use client' is required here because sorting, global text filtering,
// exchange/currency dropdown filters, refresh actions, and wipe database
// modal all require interactive React state (useState, useMemo, useCallback)
// and TanStack Table client-side hooks.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';
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
import { useWindowVirtualizer } from '@tanstack/react-virtual';
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
  FileText,
  Download,
  Upload,
  SlidersHorizontal,
  Rows3,
  LogIn,
} from 'lucide-react';
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { usePortfolioRefreshOptional } from '@/context/PortfolioRefreshContext';
import { useAuth } from '@/context/AuthContext';
import { useLanguage } from '@/context/LanguageContext';
import type { TranslationKey } from '@/lib/translations';
import { useToast } from '@/components/ui/Toast';
import { formatCurrency } from '@/lib/formatters';
import type { Position, PortfolioMetrics, AppConfig, RefreshProgressEvent } from '@/lib/types';
import {
  fetchAnalysisPrice,
  getPositions,
  getMetrics,
  streamRefresh,
  refreshInstrument,
  updateInstrument,
  wipeDatabase,
} from '@/lib/api';

const BackupExportModal = dynamic(
  () => import('@/components/BackupExportModal').then((mod) => mod.BackupExportModal),
  { ssr: false }
);

// ========================================================================== //
// Row Height (Density) Configuration & Empirical Bounds
// ========================================================================== //

/**
 * Empirical row height bounds:
 * - MIN_ROW_HEIGHT (32px): Calculated empirically so single-line ticker/price,
 *   two-line stacked dates, return badges, and 26px action buttons remain fully legible
 *   and vertically centered without any visual clipping.
 * - DEFAULT_ROW_HEIGHT (48px): Clean standard table density with balanced breathing room.
 * - MAX_ROW_HEIGHT (88px): Spacious comfortable density for large displays.
 */
const MIN_ROW_HEIGHT = 32;
const DEFAULT_ROW_HEIGHT = 48;
const MAX_ROW_HEIGHT = 88;
const ROW_HEIGHT_STORAGE_KEY = 'portfoliomaster_row_height';
const SORTING_STORAGE_KEY = 'portfoliomaster_table_sorting';

export const DEFAULT_WATCHLIST_COLUMN_WIDTHS = {
  analysis_date: 80,
  user_ticker: 105,
  company_name: 150,
  exchange: 82,
  currency: 66,
  latest_price: 104,
  daily_variation: 94,
  ytd_variation: 98,
  variation_since_analysis: 106,
  decline_to_target: 104,
  target_price: 95,
  actions: 84,
} as const;

export function clampRowHeight(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_ROW_HEIGHT;
  }
  return Math.max(MIN_ROW_HEIGHT, Math.min(MAX_ROW_HEIGHT, Math.round(value)));
}

// ========================================================================== //
// Toolbar Configuration Types & Defaults
// ========================================================================== //

interface ToolbarConfig {
  updateQuotes: boolean;
  addInstrument: boolean;
  restoreColumns: boolean;
  rowHeight: boolean;
  exportBackup: boolean;
  importValues: boolean;
  wipeDatabase: boolean;
}

const DEFAULT_TOOLBAR_CONFIG: ToolbarConfig = {
  updateQuotes: true,
  addInstrument: true,
  restoreColumns: true,
  rowHeight: false,
  exportBackup: true,
  importValues: false,
  wipeDatabase: false,
};

const TOOLBAR_STORAGE_KEY = 'portfoliomaster_toolbar_config';

const TOOLBAR_ITEMS: Array<{
  key: keyof ToolbarConfig;
  labelKey: TranslationKey;
  icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
}> = [
  {
    key: 'updateQuotes',
    labelKey: 'refreshQuotes',
    icon: RefreshCw,
    iconColor: 'text-emerald-400',
  },
  {
    key: 'addInstrument',
    labelKey: 'addInstrument',
    icon: PlusCircle,
    iconColor: 'text-emerald-400',
  },
  {
    key: 'restoreColumns',
    labelKey: 'resetColumns',
    icon: RotateCcw,
    iconColor: 'text-zinc-400',
  },
  {
    key: 'rowHeight',
    labelKey: 'rowHeightLabel',
    icon: Rows3,
    iconColor: 'text-indigo-400',
  },
  {
    key: 'exportBackup',
    labelKey: 'exportBackupLabel',
    icon: Download,
    iconColor: 'text-blue-400',
  },
  {
    key: 'importValues',
    labelKey: 'importValuesLabel',
    icon: Upload,
    iconColor: 'text-emerald-400',
  },
  {
    key: 'wipeDatabase',
    labelKey: 'wipeDatabaseLabel',
    icon: Trash2,
    iconColor: 'text-rose-400',
  },
];

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

type TranslateFn = (key: TranslationKey, params?: Record<string, string | number>) => string;

function timeAgo(isoDate: string | null | undefined, now: number, t: TranslateFn): string {
  if (!isoDate) return '';
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return '';
    const seconds = Math.floor((now - d.getTime()) / 1000);
    if (seconds < 60) return t('timeAgoSeconds');
    if (seconds < 3600) return t('timeAgoMinutes', { n: Math.floor(seconds / 60) });
    if (seconds < 86400) return t('timeAgoHours', { n: Math.floor(seconds / 3600) });
    return t('timeAgoDays', { n: Math.floor(seconds / 86400) });
  } catch {
    return '';
  }
}

export function formatStackedDate(isoDate: string | null | undefined): { dayMonth: string; year: string } | null {
  if (!isoDate || typeof isoDate !== 'string') return null;
  const parts = isoDate.split('-');
  if (parts.length >= 3 && parts[0] && parts[1] && parts[2]) {
    const year = parts[0].trim();
    const month = parts[1].trim();
    const day = parts[2].trim().slice(0, 2);
    if (day && month && year) {
      return { dayMonth: `${day}/${month}`, year };
    }
  }
  return null;
}

// ========================================================================== //
// Quote Tooltip Helper (Accessible info on hover without visual density / boxes)
// ========================================================================== //

function getQuoteTooltip(pos: Position, t: TranslateFn, now?: number): string | undefined {
  const s = pos.quote_status ? String(pos.quote_status).toUpperCase() : null;
  const statusMap: Record<string, string> = {
    FRESH: t('quoteStatusFresh'),
    DELAYED: t('quoteStatusDelayed'),
    STALE: t('quoteStatusStale'),
    UNAVAILABLE: t('quoteStatusUnavailable'),
    ERROR: t('quoteStatusError'),
  };

  const parts: string[] = [];
  if (s && statusMap[s]) {
    parts.push(statusMap[s]);
  } else if (s) {
    parts.push(s);
  }
  if (pos.quote_provider) {
    parts.push(t('quoteProviderLabel', { provider: pos.quote_provider }));
  }
  const elapsed = now === undefined ? '' : timeAgo(pos.quote_fetched_at, now, t);
  if (elapsed) {
    parts.push(elapsed);
  }
  return parts.length > 0 ? parts.join(' · ') : undefined;
}

// ========================================================================== //
// Column Sort Indicator Helper
// ========================================================================== //

function ColumnSortIndicator({
  column,
}: {
  column: { getIsSorted: () => false | 'asc' | 'desc' };
}) {
  const sorted = column.getIsSorted();
  if (sorted === 'asc') {
    return <ArrowUp className="w-3 h-3 text-emerald-400 shrink-0" />;
  }
  if (sorted === 'desc') {
    return <ArrowDown className="w-3 h-3 text-emerald-400 shrink-0" />;
  }
  return (
    <ArrowUpDown className="w-3 h-3 opacity-40 shrink-0 group-hover:opacity-80 transition-opacity" />
  );
}

// Helper: robust numeric sorting with nulls and NaNs placed deterministically at the end
function numericSortWithNulls(
  rowA: { getValue: (id: string) => unknown },
  rowB: { getValue: (id: string) => unknown },
  columnId: string
): number {
  const valA = rowA.getValue(columnId);
  const valB = rowB.getValue(columnId);
  if (valA == null && valB == null) return 0;
  if (valA == null) return 1;
  if (valB == null) return -1;
  const numA = typeof valA === 'number' ? valA : Number(valA);
  const numB = typeof valB === 'number' ? valB : Number(valB);
  const isNaNA = Number.isNaN(numA);
  const isNaNB = Number.isNaN(numB);
  if (isNaNA && isNaNB) return 0;
  if (isNaNA) return 1;
  if (isNaNB) return -1;
  return numA > numB ? 1 : numA < numB ? -1 : 0;
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
  const { t } = useLanguage();

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !loading) {
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, loading, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center overscroll-contain"
      role="dialog"
      aria-modal="true"
      aria-labelledby="wipe-modal-title"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 bg-zinc-900 border border-zinc-700 rounded-2xl shadow-2xl p-6 animate-in zoom-in-95 motion-reduce:animate-none overscroll-contain">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-5 h-5 text-rose-400" />
          </div>
          <div className="flex-1">
            <h3 id="wipe-modal-title" className="text-lg font-semibold text-white">
              {t('wipeDatabaseLabel')}
            </h3>
            <p className="mt-2 text-sm text-zinc-400 leading-relaxed">
              {t('wipeDatabaseDesc')}
            </p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium text-zinc-300 bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition-colors disabled:opacity-50"
          >
            {t('cancel')}
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-rose-600 hover:bg-rose-500 border border-rose-500 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                {t('deleting')}
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4" />
                {t('confirmWipeAll')}
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

function WatchlistRowSpacer({ height, columnCount }: { height: number; columnCount: number }) {
  if (height <= 0) return null;

  return (
    <tbody aria-hidden="true">
      <tr>
        <td colSpan={columnCount} className="p-0" style={{ height }} />
      </tr>
    </tbody>
  );
}

export function WatchlistTable({
  initialPositions,
  initialMetrics: _initialMetrics,
  appConfig,
  onDataChange,
  onEditTicker,
  onAddInstrument,
}: WatchlistTableProps) {
  const portfolioContext = usePortfolioDataOptional();
  const { user, isAuthConfigured, openAuthModal } = useAuth();
  const { language, t } = useLanguage();
  const addToast = useToast();

  // Fallback data state used only if rendered outside PortfolioProvider
  const [localPositions, setLocalPositions] = useState<Position[]>(initialPositions);

  const activePositions = useMemo(() => {
    if (portfolioContext && portfolioContext.isInitialized) {
      return portfolioContext.positions;
    }
    if (initialPositions && initialPositions.length > 0) {
      return initialPositions;
    }
    return portfolioContext ? portfolioContext.positions : localPositions;
  }, [portfolioContext, initialPositions, localPositions]);

  const activeMetrics = useMemo(() => {
    if (portfolioContext && portfolioContext.isInitialized && portfolioContext.metrics) {
      return portfolioContext.metrics;
    }
    return _initialMetrics || portfolioContext?.metrics || null;
  }, [portfolioContext, _initialMetrics]);

  const data = activePositions;
  const setData = portfolioContext ? portfolioContext.setPositions : setLocalPositions;

  // Sorting state & persistence
  const [sorting, setSorting] = useState<SortingState>([]);

  // Column sizing states & persistence
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({});

  // Toolbar customization & persistence
  const [toolbarConfig, setToolbarConfig] = useState<ToolbarConfig>(DEFAULT_TOOLBAR_CONFIG);

  // Row height (density) state & persistence
  const [rowHeight, setRowHeight] = useState<number>(DEFAULT_ROW_HEIGHT);

  // Load saved preferences safely on client mount
  useEffect(() => {
    try {
      const savedSorting = localStorage.getItem(SORTING_STORAGE_KEY);
      if (savedSorting) {
        const parsed = JSON.parse(savedSorting);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setSorting(parsed);
        }
      }
      const savedSizing = localStorage.getItem('portfoliomaster_column_sizing');
      if (savedSizing) {
        const parsed = JSON.parse(savedSizing);
        if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) {
          setColumnSizing(parsed);
        }
      }
      const savedToolbar = localStorage.getItem(TOOLBAR_STORAGE_KEY);
      if (savedToolbar) {
        const parsed = JSON.parse(savedToolbar);
        if (parsed && typeof parsed === 'object') {
          setToolbarConfig((prev) => ({ ...prev, ...parsed }));
        }
      }
      const savedHeight = localStorage.getItem(ROW_HEIGHT_STORAGE_KEY);
      if (savedHeight) {
        const parsed = parseInt(savedHeight, 10);
        if (!isNaN(parsed)) {
          setRowHeight(clampRowHeight(parsed));
        }
      }
    } catch {
      // ignore storage access errors
    }
  }, []);

  const handleSortingChange = useCallback(
    (updater: React.SetStateAction<SortingState>) => {
      setSorting((prev) => {
        const next = typeof updater === 'function' ? updater(prev) : updater;
        try {
          localStorage.setItem(SORTING_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // ignore
        }
        return next;
      });
    },
    []
  );

  const [globalFilter, setGlobalFilter] = useState('');
  const [selectedExchange, setSelectedExchange] = useState<string>('ALL');
  const [selectedCurrency, setSelectedCurrency] = useState<string>('ALL');

  const handleColumnSizingChange = useCallback(
    (updater: React.SetStateAction<ColumnSizingState>) => {
      setColumnSizing((prev) => {
        const next = typeof updater === 'function' ? updater(prev) : updater;
        try {
          if (next && typeof next === 'object' && Object.keys(next).length > 0) {
            localStorage.setItem('portfoliomaster_column_sizing', JSON.stringify(next));
          }
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
  const [refreshingTickers, setRefreshingTickers] = useState<Set<string>>(new Set());

  // Wipe database modal
  const [wipeModalOpen, setWipeModalOpen] = useState(false);
  const [wipingDb, setWipingDb] = useState(false);

  // Backup & Export modal
  const [backupModalOpen, setBackupModalOpen] = useState(false);

  const router = useRouter();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  const [rowHeightOpen, setRowHeightOpen] = useState(false);
  const rowHeightRef = useRef<HTMLDivElement>(null);

  const handleRowHeightChange = useCallback((newHeight: number) => {
    const clamped = clampRowHeight(newHeight);
    setRowHeight(clamped);
    try {
      localStorage.setItem(ROW_HEIGHT_STORAGE_KEY, String(clamped));
    } catch {
      // ignore
    }
  }, []);

  const handleToggleToolbarAction = useCallback((key: keyof ToolbarConfig) => {
    setToolbarConfig((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      try {
        localStorage.setItem(TOOLBAR_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  const handleResetToolbarConfig = useCallback(() => {
    setToolbarConfig(DEFAULT_TOOLBAR_CONFIG);
    setRowHeight(DEFAULT_ROW_HEIGHT);
    try {
      localStorage.removeItem(TOOLBAR_STORAGE_KEY);
      localStorage.removeItem(ROW_HEIGHT_STORAGE_KEY);
    } catch {
      // ignore
    }
    addToast('info', t('toolbarAndHeightResetToast'));
  }, [addToast, t]);

  // Click outside and escape key handling for settings popover
  useEffect(() => {
    if (!settingsOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSettingsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [settingsOpen]);

  // Click outside and escape key handling for row height popover
  useEffect(() => {
    if (!rowHeightOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (rowHeightRef.current && !rowHeightRef.current.contains(e.target as Node)) {
        setRowHeightOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setRowHeightOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [rowHeightOpen]);

  const handleResetColumnWidths = useCallback(() => {
    setColumnSizing({});
    try {
      localStorage.removeItem('portfoliomaster_column_sizing');
    } catch {
      // ignore
    }
    addToast('info', t('columnWidthsResetToast'));
  }, [addToast, t]);

  // Description / Notes states
  const [expandedDescriptionTickers, setExpandedDescriptionTickers] = useState<Set<string>>(new Set());
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [savingCommentTicker, setSavingCommentTicker] = useState<string | null>(null);

  // Inline Analysis Date editing states
  const [editingDateTicker, setEditingDateTicker] = useState<string | null>(null);
  const [editingDateValue, setEditingDateValue] = useState<string>('');
  const [updatingDateTickers, setUpdatingDateTickers] = useState<Set<string>>(new Set());

  const handleStartEditingDate = useCallback((ticker: string, currentDate: string | null) => {
    setEditingDateTicker(ticker);
    setEditingDateValue(currentDate || '');
  }, []);

  const handleCancelEditingDate = useCallback(() => {
    setEditingDateTicker(null);
    setEditingDateValue('');
  }, []);

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

    // Instant optimistic update with rollback support
    const rollback = portfolioContext?.optimisticUpdatePosition(ticker, { comment: newComment });
    const updated = data.map((item) =>
      item.user_ticker === ticker ? { ...item, comment: newComment } : item
    );
    setData(updated);
    if (!portfolioContext) {
      onDataChange?.(updated, activeMetrics);
    }

    try {
      await updateInstrument(ticker, { comment: newComment });
      addToast('success', t('notesSavedToast', { ticker }));
      if (portfolioContext) {
        portfolioContext.refreshPortfolioData({ silent: true });
      }
    } catch (err) {
      rollback?.();
      if (!portfolioContext) {
        setData(data);
        onDataChange?.(data, activeMetrics);
      }
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', t('notesSaveErrorToast', { ticker, error: msg }));
    } finally {
      setSavingCommentTicker(null);
    }
  }, [commentDrafts, addToast, onDataChange, activeMetrics, portfolioContext, data, setData, t]);

  // ── Reload data from API ────────────────────────────────────────────── //

  const refreshPortfolioData = portfolioContext?.refreshPortfolioData;

  const reloadData = useCallback(async () => {
    if (refreshPortfolioData) {
      await refreshPortfolioData({ silent: true });
      return;
    }
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
  }, [refreshPortfolioData, setData, onDataChange]);

  // ── Inline Analysis Date Save & Yahoo Price Recalculation ──────────── //

  const handleSaveDate = useCallback(
    async (ticker: string, newDate: string, originalDate: string | null, currency: string) => {
      const cleanNewDate = newDate.trim() || null;
      const cleanOriginalDate = originalDate?.trim() || null;

      // Close editor immediately for snappy interaction
      setEditingDateTicker(null);
      setEditingDateValue('');

      if (cleanNewDate === cleanOriginalDate) {
        return;
      }

      setUpdatingDateTickers((prev) => new Set(prev).add(ticker));

      // Instant optimistic UI update with rollback support
      const rollback = portfolioContext?.optimisticUpdatePosition(ticker, {
        analysis_date: cleanNewDate,
      });
      const updated = data.map((item) =>
        item.user_ticker === ticker ? { ...item, analysis_date: cleanNewDate } : item
      );
      setData(updated);
      if (!portfolioContext) {
        onDataChange?.(updated, activeMetrics);
      }

      try {
        await updateInstrument(ticker, { analysis_date: cleanNewDate });

        if (cleanNewDate) {
          try {
            const histRes = await fetchAnalysisPrice(ticker, cleanNewDate);
            addToast(
              'success',
              t('dateUpdatedToast', {
                ticker,
                date: cleanNewDate,
                price: formatCurrency(histRes.analysis_reference_price, currency, language),
              })
            );
          } catch (priceErr) {
            const priceMsg = priceErr instanceof Error ? priceErr.message : String(priceErr);
            addToast(
              'info',
              t('dateSavedNoYahooToast', { ticker, date: cleanNewDate, error: priceMsg })
            );
          }
        } else {
          addToast('success', t('dateRemovedToast', { ticker }));
        }

        if (portfolioContext) {
          await portfolioContext.refreshPortfolioData({ silent: true });
        } else {
          await reloadData();
        }
      } catch (err) {
        rollback?.();
        if (!portfolioContext) {
          setData(data);
          onDataChange?.(data, activeMetrics);
        }
        const msg = err instanceof Error ? err.message : String(err);
        addToast('error', t('dateUpdateErrorToast', { ticker, error: msg }));
      } finally {
        setUpdatingDateTickers((prev) => {
          const next = new Set(prev);
          next.delete(ticker);
          return next;
        });
      }
    },
    [portfolioContext, activeMetrics, onDataChange, addToast, reloadData, data, setData, language, t]
  );

  // ── Batch Refresh (Cotizaciones + Precios de Análisis) ───────────────── //

  const handleBatchRefresh = useCallback(async (onProgress?: (event: RefreshProgressEvent) => void) => {
    if (batchRefreshing) return;
    setBatchRefreshing(true);
    try {
      let completed = false;
      const quotesRes = await streamRefresh((event) => {
        if (event.type === 'complete') completed = true;
        onProgress?.(event);
      });
      if (!onProgress || !completed) await reloadData();

      if (quotesRes.status === 'fresh') {
        addToast(
          'info',
          quotesRes.message || t('quotesFreshToast')
        );
        return;
      }

      const updatedQuotes = quotesRes.updated ?? 0;
      const totalQuotes = quotesRes.total ?? 0;
      const failedQuotes = quotesRes.failed ?? 0;
      const updatedAnalysis = quotesRes.analysis_prices_updated ?? 0;
      const updatedYtd = quotesRes.ytd_prices_updated ?? 0;

      const failedPart = failedQuotes > 0 ? t('batchRefreshFailedPart', { count: failedQuotes }) : '';
      const analysisPart = updatedAnalysis > 0 ? t('batchRefreshAnalysisPart', { count: updatedAnalysis }) : '';
      const ytdPart = updatedYtd > 0 ? t('batchRefreshYtdPart', { count: updatedYtd }) : '';
      addToast(
        failedQuotes > 0 ? 'info' : 'success',
        t('batchRefreshSummaryToast', {
          updated: updatedQuotes,
          total: totalQuotes,
          failedPart,
          analysisPart,
          ytdPart,
        })
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', t('batchRefreshErrorToast', { error: msg }));
    } finally {
      setBatchRefreshing(false);
    }
  }, [batchRefreshing, addToast, reloadData, t]);

  // ── Single Row Refresh ──────────────────────────────────────────────── //

  const handleSingleRefresh = useCallback(
    async (ticker: string) => {
      if (refreshingTickers.has(ticker)) return;
      setRefreshingTickers((prev) => new Set(prev).add(ticker));
      try {
        const result = await refreshInstrument(ticker);
        if (result.status === 'ok') {
          addToast('success', t('singleQuoteUpdatedToast', { ticker }));
        } else if (result.status === 'fresh') {
          addToast('info', `${ticker}: ${result.message || t('singleQuoteFreshFallback')}`);
        } else {
          addToast('info', `${ticker}: ${result.detail || t('singleQuoteUnavailableFallback')}`);
        }
        await reloadData();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        addToast('error', t('singleQuoteErrorToast', { ticker, error: msg }));
      } finally {
        setRefreshingTickers((prev) => {
          const next = new Set(prev);
          next.delete(ticker);
          return next;
        });
      }
    },
    [refreshingTickers, addToast, reloadData, t]
  );

  // ── Wipe Database ───────────────────────────────────────────────────── //

  const handleWipeDatabase = useCallback(async () => {
    setWipingDb(true);
    try {
      await wipeDatabase();
      addToast('success', t('databaseWipedToast'));
      setData([]);
      if (portfolioContext) {
        portfolioContext.setPositions([]);
        portfolioContext.setMetrics(null);
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      onDataChange?.([], null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', t('databaseWipeErrorToast', { error: msg }));
    } finally {
      setWipingDb(false);
      setWipeModalOpen(false);
    }
  }, [addToast, onDataChange, portfolioContext, setData, t]);

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
        accessorKey: 'analysis_date',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.analysis_date,
        minSize: 70,
        maxSize: 160,
        sortingFn: (rowA, rowB, columnId) => {
          const a = rowA.getValue<string | null>(columnId);
          const b = rowB.getValue<string | null>(columnId);
          if (!a && !b) return 0;
          if (!a) return 1;
          if (!b) return -1;
          return String(a).localeCompare(String(b));
        },
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center justify-center gap-1 mx-auto hover:text-white transition-colors uppercase tracking-wider select-none text-center group/th-date text-inherit cursor-pointer"
            title={t('sortByAnalysisDate')}
          >
            <div className="flex flex-col items-center leading-tight [word-break:keep-all] whitespace-normal">
              <span>{t('colAnalysis')}</span>
              <span className="text-[0.9em] text-zinc-400 font-medium">
                {t('colDate')}
              </span>
            </div>
            <ColumnSortIndicator column={column} />
          </button>
        ),
        cell: ({ row }) => {
          const pos = row.original;
          const ticker = pos.user_ticker;
          const isEditing = editingDateTicker === ticker;
          const isUpdating = updatingDateTickers.has(ticker);

          if (isEditing) {
            return (
              <div className="flex items-center justify-center w-full" onClick={(e) => e.stopPropagation()}>
                <input
                  ref={(el) => {
                    if (el && !el.dataset.pickerOpened) {
                      el.dataset.pickerOpened = 'true';
                      try {
                        el.showPicker?.();
                      } catch {
                        // Safe fallback if browser security restricts showPicker
                      }
                    }
                  }}
                  type="date"
                  aria-label={t('analysisDateInputAria', { ticker })}
                  value={editingDateValue}
                  autoFocus
                  onChange={(e) => setEditingDateValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleSaveDate(ticker, editingDateValue, pos.analysis_date, pos.currency);
                    } else if (e.key === 'Escape') {
                      e.preventDefault();
                      handleCancelEditingDate();
                    }
                  }}
                  onBlur={() => {
                    if (editingDateValue !== (pos.analysis_date || '')) {
                      handleSaveDate(ticker, editingDateValue, pos.analysis_date, pos.currency);
                    } else {
                      handleCancelEditingDate();
                    }
                  }}
                  className="w-full max-w-[90px] bg-zinc-950 border border-emerald-500/80 rounded px-1 py-0.5 text-[11px] text-zinc-100 font-mono tabular-nums focus:outline-none focus:ring-1 focus:ring-emerald-500 shadow-sm transition-all text-center"
                />
              </div>
            );
          }

          const parsed = formatStackedDate(pos.analysis_date);

          if (parsed) {
            return (
              <button
                type="button"
                onClick={() => handleStartEditingDate(ticker, pos.analysis_date)}
                aria-label={t('editAnalysisDateAria', { date: pos.analysis_date || '', ticker })}
                className="flex flex-col items-center justify-center py-0.5 px-1 rounded-md hover:bg-zinc-800/60 cursor-pointer group/date transition-colors select-none text-center mx-auto"
                title={t('clickToEditAnalysisDate', { date: pos.analysis_date || '' })}
              >
                <div className="flex items-center gap-1">
                  <span className="text-xs font-semibold text-zinc-200 group-hover/date:text-emerald-400 font-mono tabular-nums leading-tight transition-colors">
                    {parsed.dayMonth}
                  </span>
                  {isUpdating && (
                    <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none text-emerald-400 shrink-0" />
                  )}
                </div>
                <span className="text-[10px] text-zinc-500 font-mono tabular-nums leading-none mt-0.5">
                  {parsed.year}
                </span>
              </button>
            );
          }

          return (
            <button
              type="button"
              onClick={() => handleStartEditingDate(ticker, pos.analysis_date)}
              aria-label={t('assignAnalysisDateAria', { ticker })}
              className="flex items-center justify-center py-0.5 px-1 rounded-md hover:bg-zinc-800/60 cursor-pointer group/date transition-colors select-none text-center mx-auto"
              title={t('clickToAssignAnalysisDate')}
            >
              {isUpdating ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none text-emerald-400" />
              ) : (
                <span className="text-zinc-500 group-hover/date:text-zinc-300 font-mono text-xs tabular-nums transition-colors">
                  —
                </span>
              )}
            </button>
          );
        },
      },
      {
        accessorKey: 'user_ticker',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.user_ticker,
        minSize: 70,
        maxSize: 350,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal">{t('colTicker')}</span>
            <ColumnSortIndicator column={column} />
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
                className="inline-flex flex-col px-2 py-1 rounded-lg bg-emerald-500/20 border border-emerald-400/50 shadow-[0_0_12px_rgba(16,185,129,0.35)] transition-all"
                title={t('targetReachedTooltip', {
                  price: formatCurrency(pos.latest_price, pos.currency, language),
                  target: formatCurrency(pos.target_price, pos.currency, language),
                })}
              >
                <div className="flex items-center gap-1.5">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping motion-reduce:animate-none absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
                  </span>
                  <span className="font-bold text-emerald-200 tracking-wide font-mono text-xs">
                    {pos.user_ticker}
                  </span>
                </div>
                {pos.provider_symbol && pos.provider_symbol !== pos.user_ticker && (
                  <span className="text-[10px] text-emerald-400/80 font-mono pl-3.5 leading-none">
                    {pos.provider_symbol}
                  </span>
                )}
              </div>
            );
          }

          return (
            <div className="flex flex-col">
              <span className="font-semibold text-white tracking-wide font-mono leading-tight">
                {pos.user_ticker}
              </span>
              {pos.provider_symbol && pos.provider_symbol !== pos.user_ticker && (
                <span className="text-[11px] text-zinc-500 font-mono leading-none mt-0.5">
                  {pos.provider_symbol}
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: 'company_name',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.company_name,
        minSize: 85,
        maxSize: 600,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal">
              {t('colCompany')}
            </span>
            <ColumnSortIndicator column={column} />
          </button>
        ),
        cell: ({ row }) => (
          <span className="text-zinc-200 font-medium truncate block w-full" title={row.original.company_name}>
            {row.original.company_name || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'exchange',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.exchange,
        minSize: 65,
        maxSize: 220,
        header: () => (
          <span className="uppercase tracking-wider text-inherit [word-break:keep-all] whitespace-normal">
            {t('colExchange')}
          </span>
        ),
        cell: ({ row }) => (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-mono bg-zinc-800 text-zinc-300 border border-zinc-700/60 leading-none">
            {row.original.exchange || 'AUTO'}
          </span>
        ),
      },
      {
        accessorKey: 'currency',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.currency,
        minSize: 52,
        maxSize: 160,
        header: () => (
          <span className="uppercase tracking-wider text-inherit [word-break:keep-all] whitespace-normal">
            {t('colCurrency')}
          </span>
        ),
        cell: ({ row }) => (
          <span className="text-xs font-mono text-zinc-400">
            {row.original.currency || '—'}
          </span>
        ),
      },
      {
        accessorKey: 'latest_price',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.latest_price,
        minSize: 76,
        maxSize: 320,
        sortingFn: numericSortWithNulls,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal text-right">
              {t('colLastPrice')}
            </span>
            <ColumnSortIndicator column={column} />
          </button>
        ),
        cell: ({ row }) => {
          const pos = row.original;
          return (
            <div
              className="flex items-center justify-end font-mono font-medium text-white tabular-nums leading-tight"
              title={getQuoteTooltip(pos, t)}
              onMouseEnter={(event) => {
                event.currentTarget.title = getQuoteTooltip(pos, t, Date.now()) ?? '';
              }}
            >
              {formatCurrency(pos.latest_price, pos.currency, language)}
            </div>
          );
        },
      },
      {
        accessorKey: 'daily_variation',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.daily_variation,
        minSize: 70,
        maxSize: 260,
        sortingFn: numericSortWithNulls,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal text-right">
              {t('colDayVar')}
            </span>
            <ColumnSortIndicator column={column} />
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
        accessorKey: 'ytd_variation',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.ytd_variation,
        minSize: 64,
        maxSize: 320,
        sortingFn: numericSortWithNulls,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal text-right">
              {t('colYtdVar')}
            </span>
            <ColumnSortIndicator column={column} />
          </button>
        ),
        cell: ({ row }) => {
          const { text, colorClass } = formatPercent(
            row.original.ytd_variation,
            row.original.ytd_variation_valid
          );
          return (
            <div className="flex items-center justify-end">
              <span className={colorClass}>{text}</span>
            </div>
          );
        },
      },
      {
        accessorKey: 'variation_since_analysis',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.variation_since_analysis,
        minSize: 80,
        maxSize: 320,
        sortingFn: numericSortWithNulls,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal text-right">
              {t('colAnalysisVar')}
            </span>
            <ColumnSortIndicator column={column} />
          </button>
        ),
        cell: ({ row }) => {
          const { text, colorClass } = formatPercent(
            row.original.variation_since_analysis,
            row.original.variation_since_analysis_valid
          );
          return (
            <div className="flex items-center justify-end">
              <span className={colorClass}>{text}</span>
            </div>
          );
        },
      },
      {
        accessorFn: (row) =>
          row.decline_to_target_valid && row.decline_to_target !== null
            ? row.decline_to_target
            : null,
        id: 'decline_to_target',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.decline_to_target,
        minSize: 82,
        maxSize: 320,
        sortingFn: numericSortWithNulls,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal text-right">
              {t('colToTarget')}
            </span>
            <ColumnSortIndicator column={column} />
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
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.target_price,
        minSize: 76,
        maxSize: 260,
        sortingFn: numericSortWithNulls,
        header: ({ column }) => (
          <button
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="flex items-center gap-1 justify-end w-full hover:text-white transition-colors uppercase tracking-wider text-inherit cursor-pointer"
          >
            <span className="[word-break:keep-all] whitespace-normal text-right">
              {t('colTargetPrice')}
            </span>
            <ColumnSortIndicator column={column} />
          </button>
        ),
        cell: ({ row }) => (
          <div className="flex justify-end font-mono text-zinc-300">
            {formatCurrency(row.original.target_price, row.original.currency, language)}
          </div>
        ),
      },
      // Actions column — per-row description, edit & refresh
      {
        id: 'actions',
        size: DEFAULT_WATCHLIST_COLUMN_WIDTHS.actions,
        minSize: 78,
        maxSize: 105,
        enableResizing: false,
        header: '',
        cell: ({ row }) => {
          const ticker = row.original.user_ticker;
          const isRefreshing = refreshingTickers.has(ticker);
          const isExpanded = expandedDescriptionTickers.has(ticker);
          const hasComment = Boolean(row.original.comment && row.original.comment.trim());

          return (
            <div className="flex items-center justify-end gap-0.5">
              {/* Description toggle button */}
              <button
                type="button"
                onClick={() => toggleDescription(ticker)}
                aria-label={t('toggleNotesAria', { ticker })}
                className={`p-1 rounded-lg transition-all relative ${
                  isExpanded
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/40'
                    : hasComment
                    ? 'text-blue-400 hover:text-blue-300 hover:bg-blue-500/10'
                    : 'text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800'
                }`}
                title={
                  hasComment
                    ? t('notesPreviewTooltip', {
                        preview: `${row.original.comment.slice(0, 60)}${row.original.comment.length > 60 ? '...' : ''}`,
                      })
                    : t('addNotesTooltip', { ticker })
                }
              >
                <FileText className="w-3.5 h-3.5" />
                {hasComment && (
                  <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-blue-400" />
                )}
              </button>

              {/* Edit instrument modal button */}
              <button
                type="button"
                onClick={() => onEditTicker?.(ticker)}
                aria-label={t('editTickerAria', { ticker })}
                className="p-1 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200 transition-all"
                title={t('editTickerTooltip', { ticker })}
              >
                <Edit3 className="w-3.5 h-3.5" />
              </button>

              {/* Refresh quote button */}
              <button
                type="button"
                onClick={() => handleSingleRefresh(ticker)}
                disabled={isRefreshing || batchRefreshing}
                aria-label={t('refreshTickerAria', { ticker })}
                className="p-1 rounded-lg hover:bg-zinc-800 text-zinc-500 hover:text-emerald-400 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                title={t('refreshTickerTooltip', { ticker })}
              >
                {isRefreshing ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none text-emerald-400" />
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
      editingDateTicker,
      editingDateValue,
      updatingDateTickers,
      handleStartEditingDate,
      handleCancelEditingDate,
      handleSaveDate,
      refreshingTickers,
      batchRefreshing,
      handleSingleRefresh,
      onEditTicker,
      expandedDescriptionTickers,
      toggleDescription,
      language,
      t,
    ]
  );

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: filteredData,
    columns,
    getRowId: (row) => row.user_ticker,
    state: {
      sorting,
      columnSizing,
    },
    onSortingChange: handleSortingChange,
    onColumnSizingChange: handleColumnSizingChange,
    columnResizeMode: 'onChange',
    enableColumnResizing: true,
    autoResetPageIndex: false,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const rows = table.getRowModel().rows;
  const tableHeaderRef = useRef<HTMLTableSectionElement>(null);
  const [scrollMargin, setScrollMargin] = useState(0);
  const getItemKey = useCallback((index: number) => rows[index].id, [rows]);
  const rowVirtualizer = useWindowVirtualizer<HTMLTableSectionElement>({
    count: rows.length,
    getItemKey,
    estimateSize: () => rowHeight,
    initialRect: { height: 640, width: 0 },
    overscan: 6,
    scrollMargin,
  });

  useEffect(() => {
    const header = tableHeaderRef.current;
    if (!header) return;

    const observer = new ResizeObserver(() => {
      setScrollMargin(header.getBoundingClientRect().bottom + window.scrollY);
    });
    observer.observe(header);
    observer.observe(document.body);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    rowVirtualizer.measure();
  }, [rowHeight, rowVirtualizer]);

  const visibleRows = rowVirtualizer.getVirtualItems();
  const topSpace = (visibleRows[0]?.start ?? scrollMargin) - scrollMargin;
  const visibleEnd = (visibleRows.at(-1)?.end ?? scrollMargin) - scrollMargin;
  const bottomSpace = rowVirtualizer.getTotalSize() - visibleEnd;

  const cellPaddingClass = useMemo(() => {
    if (rowHeight <= 34) return 'py-1 px-2';
    if (rowHeight <= 42) return 'py-1.5 px-2.5';
    return 'py-3 px-2.5';
  }, [rowHeight]);

  return (
    <div className="flex flex-col gap-4 relative">
      {/* Wipe Database Modal */}
      <WipeDatabaseModal
        open={wipeModalOpen}
        onClose={() => setWipeModalOpen(false)}
        onConfirm={handleWipeDatabase}
        loading={wipingDb}
      />

      {/* Backup & Export Modal */}
      <BackupExportModal
        isOpen={backupModalOpen}
        onClose={() => setBackupModalOpen(false)}
        onDataRestored={portfolioContext ? undefined : reloadData}
      />

      {/* Search, Filters & Action Buttons Bar */}
      <div className="relative z-30 flex flex-col 2xl:flex-row items-stretch 2xl:items-center justify-between gap-3 bg-zinc-900/80 backdrop-blur border border-zinc-800 p-2.5 sm:p-3 rounded-xl">
        {/* Left side: Search & Filter Controls */}
        <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
          {/* Search Input */}
          <div className="relative min-w-[160px] sm:min-w-[200px] max-w-xs flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
            <input
              type="text"
              aria-label={t('searchAria')}
              placeholder={t('searchPlaceholder')}
              value={globalFilter}
              onChange={(e) => setGlobalFilter(e.target.value)}
              className="w-full bg-zinc-950/70 border border-zinc-800 rounded-lg pl-9 pr-3 py-1.5 text-xs sm:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 transition-all font-sans h-9"
            />
          </div>

          {/* Mercado Filter */}
          <div className="flex items-center gap-1.5 bg-zinc-950/50 border border-zinc-800 rounded-lg px-2.5 h-9 shrink-0">
            <Filter className="w-3.5 h-3.5 text-zinc-400" />
            <label htmlFor="watchlist-exchange-filter" className="text-xs text-zinc-400">
              {t('exchangeFilterLabel')}
            </label>
            <select
              id="watchlist-exchange-filter"
              aria-label={t('exchangeFilterAria')}
              value={selectedExchange}
              onChange={(e) => setSelectedExchange(e.target.value)}
              className="bg-transparent text-xs text-zinc-200 font-medium focus:outline-none cursor-pointer pr-1"
            >
              <option value="ALL" className="bg-zinc-900 text-zinc-200">{t('allExchanges')}</option>
              {exchanges.map((ex) => (
                <option key={ex} value={ex} className="bg-zinc-900 text-zinc-200">
                  {ex}
                </option>
              ))}
            </select>
          </div>

          {/* Divisa Filter */}
          <div className="flex items-center gap-1.5 bg-zinc-950/50 border border-zinc-800 rounded-lg px-2.5 h-9 shrink-0">
            <label htmlFor="watchlist-currency-filter" className="text-xs text-zinc-400">
              {t('currencyFilterLabel')}
            </label>
            <select
              id="watchlist-currency-filter"
              aria-label={t('currencyFilterAria')}
              value={selectedCurrency}
              onChange={(e) => setSelectedCurrency(e.target.value)}
              className="bg-transparent text-xs text-zinc-200 font-medium focus:outline-none cursor-pointer pr-1"
            >
              <option value="ALL" className="bg-zinc-900 text-zinc-200">{t('allCurrencies')}</option>
              {currencies.map((curr) => (
                <option key={curr} value={curr} className="bg-zinc-900 text-zinc-200">
                  {curr}
                </option>
              ))}
            </select>
          </div>

          {/* Counter Badge */}
          <div className="inline-flex items-center text-xs text-zinc-400 px-2.5 h-9 font-mono whitespace-nowrap shrink-0 bg-zinc-950/40 border border-zinc-800/80 rounded-lg">
            {t('showingLabel')}{' '}
            <span className="text-zinc-200 font-semibold mx-1">{filteredData.length}</span>{' '}
            {t('ofLabel')}{' '}
            <span className="text-zinc-200 font-semibold ml-1">{data.length}</span>
          </div>
        </div>

        {/* Right side: Action Buttons */}
        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          {/* Add Instrument Button */}
          {toolbarConfig.addInstrument && onAddInstrument && (
            <button
              onClick={onAddInstrument}
              className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
                bg-zinc-800/90 text-zinc-200 border border-zinc-700
                hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
              title={t('addInstrumentTooltip')}
            >
              <PlusCircle className="w-4 h-4 text-emerald-400" />
              <span className="hidden sm:inline">{t('addInstrument')}</span>
            </button>
          )}

          {/* Quick Import Values Button */}
          {toolbarConfig.importValues && (
            <button
              onClick={() => router.push('/import')}
              className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
                bg-zinc-800/90 text-zinc-200 border border-zinc-700
                hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
              title={t('importValuesTooltip')}
            >
              <Upload className="w-4 h-4 text-emerald-400" />
              <span className="hidden sm:inline">{t('import')}</span>
            </button>
          )}

          {/* Export / Backup Button */}
          {toolbarConfig.exportBackup && (
            <button
              onClick={() => setBackupModalOpen(true)}
              className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
                bg-zinc-800/90 text-zinc-200 border border-zinc-700
                hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm shrink-0"
              title={t('exportBackupTooltip')}
            >
              <Download className="w-4 h-4 text-blue-400" />
              <span className="hidden sm:inline">{t('exportBackupLabel')}</span>
            </button>
          )}

          {/* Batch Refresh (Cotizaciones + Precios de Análisis) */}
          {toolbarConfig.updateQuotes && (
            <WatchlistRefreshButton
              appConfig={appConfig}
              batchRefreshing={batchRefreshing}
              isEmpty={data.length === 0}
              onRefresh={handleBatchRefresh}
            />
          )}

          {/* Reset Column Widths Button */}
          {toolbarConfig.restoreColumns && (
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
                  ? t('resetColumnsTooltip')
                  : t('columnsAlreadyDefaultTooltip')
              }
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span className="hidden xl:inline">{t('resetColumns')}</span>
            </button>
          )}

          {/* Row Height Controller Button & Popover */}
          {toolbarConfig.rowHeight && (
            <div className="relative" ref={rowHeightRef}>
              <button
                onClick={() => setRowHeightOpen((prev) => !prev)}
                aria-label={t('adjustRowHeightAria')}
                aria-expanded={rowHeightOpen}
                className={`h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all shrink-0 border cursor-pointer ${
                  rowHeightOpen
                    ? 'bg-zinc-800 text-indigo-400 border-zinc-600 ring-1 ring-indigo-500/40 shadow-sm'
                    : 'bg-zinc-800/90 text-zinc-200 border border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm'
                }`}
                title={t('adjustRowHeightTooltip')}
              >
                <Rows3 className="w-3.5 h-3.5 text-indigo-400" />
                <span>{t('rowHeightShort')} · {rowHeight}px</span>
              </button>

              {rowHeightOpen && (
                <div
                  className="absolute right-0 top-full mt-2 w-[calc(100vw-2rem)] sm:w-96 rounded-2xl bg-zinc-900 border border-zinc-800 shadow-2xl p-4 z-[100] animate-in fade-in zoom-in-95 motion-reduce:animate-none duration-150 space-y-3.5"
                >
                  {/* Popover Header */}
                  <div className="flex items-center justify-between pb-2.5 border-b border-zinc-800/80">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-md bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center">
                        <Rows3 className="w-3.5 h-3.5" />
                      </div>
                      <div>
                        <span className="text-xs font-semibold text-white tracking-tight">
                          {t('rowHeightLabel')}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono ml-2">
                          {rowHeight <= 36 ? t('densityCompact') : rowHeight <= 54 ? t('densityStandard') : t('densitySpacious')}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleRowHeightChange(DEFAULT_ROW_HEIGHT)}
                        aria-label={t('rowHeightResetAria')}
                        className="text-[11px] text-zinc-400 hover:text-indigo-400 font-medium flex items-center gap-1 transition-colors cursor-pointer"
                        title={t('rowHeightResetTitle')}
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>48px</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setRowHeightOpen(false)}
                        aria-label={t('closeRowHeightAria')}
                        className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60 transition-colors cursor-pointer"
                        title={t('close')}
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Slider & Numeric Input */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <label htmlFor="watchlist-row-height-number" className="text-zinc-400 font-medium">
                        {t('verticalDensity')}
                      </label>
                      <div className="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1 focus-within:border-indigo-500/80 focus-within:ring-1 focus-within:ring-indigo-500">
                        <input
                          id="watchlist-row-height-number"
                          type="number"
                          aria-label={t('rowHeightNumberAria')}
                          min={MIN_ROW_HEIGHT}
                          max={MAX_ROW_HEIGHT}
                          value={rowHeight}
                          onChange={(e) => {
                            const val = parseInt(e.target.value, 10);
                            if (!isNaN(val)) {
                              handleRowHeightChange(val);
                            }
                          }}
                          className="w-12 bg-transparent text-right font-mono text-xs text-white focus:outline-none"
                        />
                        <span className="text-zinc-500 font-mono text-[11px]">px</span>
                      </div>
                    </div>

                    <input
                      type="range"
                      aria-label={t('rowHeightSliderAria')}
                      min={MIN_ROW_HEIGHT}
                      max={MAX_ROW_HEIGHT}
                      step={1}
                      value={rowHeight}
                      onChange={(e) => handleRowHeightChange(parseInt(e.target.value, 10))}
                      className="w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-indigo-500 hover:accent-indigo-400 transition-all"
                    />

                    <div className="flex justify-between text-[10px] text-zinc-500 font-mono">
                      <span>{MIN_ROW_HEIGHT}px ({t('minLabel')})</span>
                      <span>{DEFAULT_ROW_HEIGHT}px ({t('defaultLabel')})</span>
                      <span>{MAX_ROW_HEIGHT}px ({t('maxLabel')})</span>
                    </div>
                  </div>

                  {/* Preset Buttons */}
                  <div className="flex items-center gap-1.5">
                    {[
                      { label: t('densityCompact'), val: 34 },
                      { label: t('densityStandard'), val: 48 },
                      { label: t('densitySpacious'), val: 64 },
                    ].map((preset) => (
                      <button
                        key={preset.val}
                        onClick={() => handleRowHeightChange(preset.val)}
                        className={`flex-1 py-1 rounded-md text-[11px] font-medium border transition-colors cursor-pointer ${
                          rowHeight === preset.val
                            ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40 shadow-sm'
                            : 'bg-zinc-800/60 text-zinc-400 border-zinc-700/60 hover:bg-zinc-800 hover:text-zinc-200'
                        }`}
                      >
                        {preset.label} · {preset.val}px
                      </button>
                    ))}
                  </div>

                  {/* Minimum Warning Notice */}
                  {rowHeight <= MIN_ROW_HEIGHT && (
                    <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs animate-in fade-in motion-reduce:animate-none duration-150">
                      <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                      <div className="leading-relaxed">
                        <span className="font-semibold text-amber-200">
                          {t('minRowHeightReached')} ({MIN_ROW_HEIGHT}px).
                        </span>{' '}
                        {t('minRowHeightDesc')}
                      </div>
                    </div>
                  )}

                  {/* 2-Row Sample Live Preview */}
                  <div className="pt-2 border-t border-zinc-800/80 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">
                        {t('livePreviewRows')}
                      </span>
                      <span className="text-[10px] text-zinc-500 font-mono">
                        {rowHeight}px
                      </span>
                    </div>

                    <div className="rounded-lg border border-zinc-800/90 bg-zinc-950/70 overflow-hidden shadow-inner">
                      <table className="w-full text-left text-xs text-zinc-300 table-fixed">
                        <thead className="bg-zinc-900/90 text-[10px] text-zinc-400 border-b border-zinc-800 uppercase tracking-wider">
                          <tr>
                            <th className="py-1 px-2.5 w-[34%]">{t('colTicker')}</th>
                            <th className="py-1 px-2 text-right w-[24%]">{t('colPriceShort')}</th>
                            <th className="py-1 px-2 text-right w-[24%]">Var.</th>
                            <th className="py-1 px-2 text-center w-[18%]">{t('colActions')}</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800/60 font-sans">
                          {/* Sample Row 1: AAPL */}
                          <tr
                            style={{ height: `${rowHeight}px` }}
                            className="hover:bg-zinc-850/40 transition-colors"
                          >
                            <td className={`${cellPaddingClass} align-middle overflow-hidden`}>
                              <div className="flex flex-col min-w-0">
                                <span className="font-semibold text-white font-mono text-xs leading-none">
                                  AAPL
                                </span>
                                {rowHeight > 42 && (
                                  <span className="text-[10px] text-zinc-500 truncate leading-tight mt-0.5">
                                    Apple Inc.
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className={`${cellPaddingClass} text-right align-middle overflow-hidden font-mono text-xs text-white`}>
                              $232.50
                            </td>
                            <td className={`${cellPaddingClass} text-right align-middle overflow-hidden`}>
                              <span className="inline-flex items-center gap-0.5 text-emerald-400 font-semibold font-mono text-xs">
                                <TrendingUp className="w-3 h-3 shrink-0" />
                                +1.45%
                              </span>
                            </td>
                            <td className={`${cellPaddingClass} text-center align-middle overflow-hidden`}>
                              <div className="inline-flex items-center justify-center gap-1 text-zinc-400">
                                <span className="p-1 rounded text-blue-400 bg-blue-500/10">
                                  <FileText className="w-3 h-3" />
                                </span>
                                <span className="p-1 rounded text-zinc-500">
                                  <Edit3 className="w-3 h-3" />
                                </span>
                              </div>
                            </td>
                          </tr>

                          {/* Sample Row 2: BME:MAP */}
                          <tr
                            style={{ height: `${rowHeight}px` }}
                            className="hover:bg-zinc-850/40 transition-colors"
                          >
                            <td className={`${cellPaddingClass} align-middle overflow-hidden`}>
                              <div className="flex flex-col min-w-0">
                                <span className="font-semibold text-white font-mono text-xs leading-none">
                                  BME:MAP
                                </span>
                                {rowHeight > 42 && (
                                  <span className="text-[10px] text-zinc-500 truncate leading-tight mt-0.5">
                                    Mapfre S.A.
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className={`${cellPaddingClass} text-right align-middle overflow-hidden font-mono text-xs text-white`}>
                              2.38 €
                            </td>
                            <td className={`${cellPaddingClass} text-right align-middle overflow-hidden`}>
                              <span className="inline-flex items-center gap-0.5 text-rose-400 font-semibold font-mono text-xs">
                                <TrendingDown className="w-3 h-3 shrink-0" />
                                -0.62%
                              </span>
                            </td>
                            <td className={`${cellPaddingClass} text-center align-middle overflow-hidden`}>
                              <div className="inline-flex items-center justify-center gap-1 text-zinc-400">
                                <span className="p-1 rounded text-zinc-500">
                                  <FileText className="w-3 h-3" />
                                </span>
                                <span className="p-1 rounded text-zinc-500">
                                  <Edit3 className="w-3 h-3" />
                                </span>
                              </div>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Wipe Database */}
          {toolbarConfig.wipeDatabase && (
            <button
              onClick={() => setWipeModalOpen(true)}
              disabled={batchRefreshing || wipingDb}
              className="h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all
                bg-rose-500/5 text-zinc-500 border border-zinc-800
                hover:bg-rose-500/10 hover:text-rose-400 hover:border-rose-500/30
                disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
              title={t('wipeDatabaseTooltip')}
            >
              <Trash2 className="w-4 h-4" />
              <span className="hidden sm:inline">{t('wipeDb')}</span>
            </button>
          )}

          {/* Settings / Customize Toolbar Popover */}
          <div className="relative" ref={settingsRef}>
            <button
              onClick={() => setSettingsOpen((prev) => !prev)}
              aria-label={t('customizeToolbarAria')}
              aria-expanded={settingsOpen}
              className={`h-9 w-9 inline-flex items-center justify-center rounded-lg text-xs font-medium transition-all shrink-0 border cursor-pointer ${
                settingsOpen
                  ? 'bg-zinc-800 text-emerald-400 border-zinc-600 ring-1 ring-emerald-500/40'
                  : 'bg-zinc-800/90 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm'
              }`}
              title={t('customizeToolbarTooltip')}
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>

            {settingsOpen && (
              <div
                className="absolute right-0 top-full mt-2 w-[calc(100vw-2rem)] sm:w-80 rounded-xl bg-zinc-900 border border-zinc-800 shadow-2xl p-3.5 z-[100] animate-in fade-in zoom-in-95 motion-reduce:animate-none duration-150"
              >
                <div className="flex items-center justify-between pb-2.5 border-b border-zinc-800/80">
                  <div className="flex items-center gap-2">
                    <SlidersHorizontal className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-xs font-semibold text-white tracking-tight">
                      {t('customizeToolbar')}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSettingsOpen(false)}
                    aria-label={t('closeToolbarSettingsAria')}
                    className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60 transition-colors cursor-pointer"
                    title={t('close')}
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <p className="text-[11px] text-zinc-400 mt-2 mb-2 leading-relaxed">
                  {t('customizeToolbarDesc')}
                </p>

                <div className="space-y-1">
                  {TOOLBAR_ITEMS.map((item) => {
                    const isEnabled = toolbarConfig[item.key];
                    const Icon = item.icon;
                    const itemLabel = t(item.labelKey);

                    return (
                      <button
                        key={item.key}
                        type="button"
                        role="switch"
                        aria-checked={isEnabled}
                        onClick={() => handleToggleToolbarAction(item.key)}
                        className="w-full flex items-center justify-between p-2 rounded-lg hover:bg-zinc-800/60 cursor-pointer select-none transition-colors group text-left"
                      >
                        <div className="flex items-center gap-2.5 min-w-0 pr-2">
                          <Icon className={`w-3.5 h-3.5 shrink-0 ${item.iconColor}`} />
                          <span className="text-xs text-zinc-300 group-hover:text-white font-medium truncate">
                            {itemLabel}
                          </span>
                        </div>
                        <div
                          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors motion-reduce:transition-none duration-200 ease-in-out ${
                            isEnabled ? 'bg-emerald-600' : 'bg-zinc-800 border border-zinc-700'
                          }`}
                        >
                          <span
                            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-md ring-0 transition motion-reduce:transition-none duration-200 ease-in-out ${
                              isEnabled ? 'translate-x-4' : 'translate-x-0'
                            }`}
                          />
                        </div>
                      </button>
                    );
                  })}
                </div>

                <div className="pt-2.5 mt-2 border-t border-zinc-800/80 flex items-center justify-between">
                  <button
                    onClick={handleResetToolbarConfig}
                    className="text-[11px] text-zinc-400 hover:text-emerald-400 font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
                    title={t('resetToolbarTooltip')}
                  >
                    <RotateCcw className="w-3 h-3" />
                    <span>{t('resetDefaults')}</span>
                  </button>
                  <span className="text-[10px] text-zinc-600 font-mono">localStorage</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Table Container */}
      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900/40 backdrop-blur shadow-2xl">
        <table
          className="w-full table-fixed text-left text-sm text-zinc-300"
          style={
            {
              width: `${table.getTotalSize()}px`,
              minWidth: '100%',
              '--watchlist-row-height': `${rowHeight}px`,
            } as React.CSSProperties
          }
        >
          <thead ref={tableHeaderRef} className="border-b border-zinc-800/80 bg-zinc-950/70 text-zinc-400">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const headerSize = header.getSize();
                  const headerPaddingClass =
                    headerSize < 75
                      ? 'py-2 px-1.5 pr-2'
                      : headerSize < 100
                      ? 'py-2.5 px-2.5 pr-2.5'
                      : 'py-3 px-3.5 pr-3';

                  const headerFontClass =
                    headerSize < 80
                      ? 'text-[9.5px] leading-[1.08]'
                      : headerSize < 110
                      ? 'text-[11px] leading-tight'
                      : 'text-xs leading-normal';

                  return (
                    <th
                      key={header.id}
                      scope="col"
                      style={{ width: `${headerSize}px` }}
                      className={`${headerPaddingClass} ${headerFontClass} font-semibold text-zinc-400 relative select-none group/th align-middle`}
                    >
                      <div className="w-full [word-break:keep-all] whitespace-normal [overflow-wrap:normal]">
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
                          title={t('resizerTooltip')}
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
                  );
                })}
              </tr>
            ))}
          </thead>
          <WatchlistRowSpacer height={topSpace} columnCount={columns.length} />
          {visibleRows.map((virtualRow) => {
            const row = rows[virtualRow.index];
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
              <tbody
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={rowVirtualizer.measureElement}
                className="font-sans"
              >
                <tr
                  className={`group border-b border-zinc-800/60 transition-colors hover:bg-zinc-800/30 ${
                    isRefreshingRow ? 'opacity-60' : ''
                  } ${isExpanded ? 'bg-zinc-850/60' : ''}`}
                  style={{ height: `${rowHeight}px` }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={{
                        width: `${cell.column.getSize()}px`,
                        height: `${rowHeight}px`,
                      }}
                      className={`${cellPaddingClass} ${
                        cell.column.id === 'actions' ? '!px-1.5' : ''
                      } align-middle overflow-hidden`}
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
                      <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4 space-y-3 shadow-lg animate-in fade-in-50 motion-reduce:animate-none duration-150">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                              <FileText className="w-4 h-4" />
                            </div>
                            <div>
                              <span className="text-xs font-semibold text-white">
                                {t('companyNotesTitle')}
                              </span>
                              <span className="text-xs text-zinc-400 ml-2 font-mono">
                                {row.original.user_ticker} · {row.original.company_name}
                              </span>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => toggleDescription(ticker)}
                            aria-label={t('closeNotesAria', { ticker })}
                            className="text-zinc-500 hover:text-zinc-300 p-1 rounded-lg hover:bg-zinc-800 transition"
                            title={t('closeNotesTooltip')}
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>

                        <textarea
                          value={currentComment}
                          aria-label={t('notesTextareaAria', { ticker })}
                          onChange={(e) =>
                            handleCommentChange(ticker, e.target.value)
                          }
                          placeholder={t('notesPlaceholder', { company: row.original.company_name })}
                          rows={3}
                          className="w-full bg-zinc-900/90 border border-zinc-800 rounded-lg p-3 text-xs sm:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all font-sans leading-relaxed resize-y"
                        />

                        <div className="flex items-center justify-between text-xs pt-0.5">
                          <span className="text-zinc-500 text-[11px] font-mono">
                            {currentComment.length} {t('charactersLabel')}
                            {hasUnsavedChanges && (
                              <span className="ml-2 text-amber-400">
                                • {t('unsavedChanges')}
                              </span>
                            )}
                          </span>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => toggleDescription(ticker)}
                              className="px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
                            >
                              {t('close')}
                            </button>
                            <button
                              onClick={() => handleSaveComment(row.original)}
                              disabled={savingCommentTicker === ticker}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
                            >
                              {savingCommentTicker === ticker ? (
                                <>
                                  <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                                  {t('saving')}
                                </>
                              ) : (
                                <>
                                  <Check className="w-3.5 h-3.5" />
                                  {t('saveDescription')}
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            );
          })}
          <WatchlistRowSpacer height={bottomSpace} columnCount={columns.length} />
          <tbody className="font-sans">
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="py-12 sm:py-16 px-4 text-center text-zinc-400"
                >
                  {isAuthConfigured && !user && data.length === 0 ? (
                    <div className="sticky left-4 sm:static flex flex-col items-center justify-center gap-3 max-w-[calc(100vw-3rem)] sm:max-w-sm mx-auto py-4">
                      <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shadow-sm">
                        <LogIn className="w-6 h-6" />
                      </div>
                      <p className="text-sm font-semibold text-white">
                        {t('signInPortfolioTitle')}
                      </p>
                      <p className="text-xs text-zinc-400 text-center leading-relaxed">
                        {t('signInPortfolioDesc')}
                      </p>
                      <button
                        onClick={() => openAuthModal()}
                        className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-zinc-950 bg-emerald-400 hover:bg-emerald-300 transition-colors shadow-lg shadow-emerald-950/40"
                      >
                        <LogIn className="w-4 h-4" />
                        {t('signIn')}
                      </button>
                    </div>
                  ) : portfolioContext && !portfolioContext.isInitialized && data.length === 0 ? (
                    <div className="sticky left-4 sm:static flex flex-col items-center justify-center gap-2.5 max-w-[calc(100vw-3rem)] sm:max-w-sm mx-auto">
                      <Loader2 className="w-8 h-8 text-emerald-400 animate-spin motion-reduce:animate-none" />
                      <p className="text-sm font-medium text-zinc-300">
                        {t('loadingWatchlist')}
                      </p>
                      <p className="text-xs text-zinc-500">
                        {t('syncingQuotes')}
                      </p>
                    </div>
                  ) : (
                    <div className="sticky left-4 sm:static flex flex-col items-center justify-center gap-2.5 max-w-[calc(100vw-3rem)] sm:max-w-sm mx-auto">
                      <Info className="w-8 h-8 text-zinc-600" />
                      <p className="text-sm font-medium text-zinc-300">
                        {data.length === 0 ? t('emptyWatchlist') : t('emptyFilters')}
                      </p>
                      <p className="text-xs text-zinc-500">
                        {data.length === 0 ? t('emptyWatchlistHint') : t('emptyFiltersHint')}
                      </p>
                      {data.length === 0 && onAddInstrument && (
                        <button
                          onClick={onAddInstrument}
                          className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-950/40"
                        >
                          <PlusCircle className="w-4 h-4" />
                          {t('addFirstInstrument')}
                        </button>
                      )}
                    </div>
                  )}
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
                title={t('addNewInstrumentRowTitle')}
              >
                <td
                  colSpan={columns.length}
                  className="py-3 px-4 text-left"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center group-hover:bg-emerald-500/20 group-hover:border-emerald-500/40 group-hover:scale-105 motion-reduce:group-hover:scale-100 transition-all text-emerald-400 shrink-0">
                      <PlusCircle className="w-3.5 h-3.5" />
                    </span>
                    <span className="text-xs font-semibold text-emerald-400 group-hover:text-emerald-300 transition-colors">
                      {t('addNewInstrumentRow')}
                    </span>
                    <span className="hidden sm:inline text-[11px] text-zinc-500 group-hover:text-zinc-400 transition-colors">
                      {t('addNewInstrumentRowHint')}
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
            <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none text-emerald-400" />
            <span className="text-sm text-zinc-200 font-medium">
              {t('updatingYahoo')}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function WatchlistRefreshButton({ appConfig, batchRefreshing, isEmpty, onRefresh }: {
  appConfig?: AppConfig | null;
  batchRefreshing: boolean;
  isEmpty: boolean;
  onRefresh: (onProgress?: (event: RefreshProgressEvent) => void) => Promise<void>;
}) {
  const refresh = usePortfolioRefreshOptional();
  const { t } = useLanguage();
  const config = refresh?.config ?? appConfig;
  const isAnyRefreshing = batchRefreshing || (refresh ? refresh.isRefreshing : Boolean(config?.is_refreshing));
  const currentBatch = refresh?.batchProgress?.currentBatch ?? config?.current_batch ?? 0;
  const totalBatches = refresh?.batchProgress?.totalBatches ?? config?.total_batches ?? 0;
  const processed = refresh?.batchProgress?.processed ?? config?.processed_symbols ?? 0;
  const total = refresh?.batchProgress?.total ?? config?.total_symbols ?? 0;
  return (
    <button
      onClick={() => onRefresh(refresh?.applyStreamEvent)}
      disabled={isAnyRefreshing || isEmpty}
      aria-label={t('refreshQuotes')}
      className="h-9 inline-flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium transition-all
        bg-emerald-500/10 text-emerald-400 border border-emerald-500/20
        hover:bg-emerald-500/20 hover:text-emerald-300 hover:border-emerald-500/40
        disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
      title={t('refreshQuotesTooltip')}
    >
      {isAnyRefreshing ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none text-amber-400" />
          <span className="hidden sm:inline text-amber-300">
            {currentBatch > 0 && totalBatches > 0
              ? t('updatingProgress', { current: currentBatch, total: totalBatches, processed, symbols: total })
              : t('refreshing')}
          </span>
        </>
      ) : (
        <>
          <RefreshCw className="w-4 h-4" />
          <span className="hidden sm:inline">{t('refreshQuotes')}</span>
        </>
      )}
    </button>
  );
}
