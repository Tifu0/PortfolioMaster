'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import {
  ColumnSizingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from '@tanstack/react-table';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import { Loader2 } from 'lucide-react';
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { useAuth } from '@/context/AuthContext';
import { useLanguage } from '@/context/LanguageContext';
import { useToast } from '@/components/ui/Toast';
import {
  getStoredJson,
  getStoredString,
  removeStoredItem,
  setStoredJson,
  setStoredString,
} from '@/lib/storage';
import {
  COLUMN_SIZING_STORAGE_KEY,
  DEFAULT_ROW_HEIGHT,
  ROW_HEIGHT_STORAGE_KEY,
  SORTING_STORAGE_KEY,
  clampRowHeight,
  filterWatchlistPositions,
  getRowCellPaddingClass,
} from '@/lib/watchlist-formatters';
import type { Position, PortfolioMetrics, AppConfig } from '@/lib/types';
import { buildWatchlistColumns } from '@/components/watchlist/watchlistColumns';
import { InstrumentDescriptionPanel } from '@/components/watchlist/InstrumentDescriptionPanel';
import { WipeDatabaseModal } from '@/components/watchlist/WipeDatabaseModal';
import { WatchlistEmptyState } from '@/components/watchlist/WatchlistEmptyState';
import { useWatchlistActions } from '@/components/watchlist/useWatchlistActions';
import {
  DEFAULT_TOOLBAR_CONFIG,
  TOOLBAR_STORAGE_KEY,
  WatchlistToolbar,
  isPartialToolbarConfig,
  type ToolbarConfig,
} from '@/components/watchlist/WatchlistToolbar';

export {
  DEFAULT_WATCHLIST_COLUMN_WIDTHS,
  clampRowHeight,
  formatStackedDate,
} from '@/lib/watchlist-formatters';

const BackupExportModal = dynamic(
  () => import('@/components/BackupExportModal').then((mod) => mod.BackupExportModal),
  { ssr: false }
);

export interface WatchlistTableProps {
  initialPositions: Position[];
  initialMetrics?: PortfolioMetrics | null;
  appConfig?: AppConfig | null;
  onDataChange?: (positions: Position[], metrics: PortfolioMetrics | null) => void;
  onEditTicker?: (ticker: string) => void;
  onAddInstrument?: () => void;
}

const isSortingState = (value: unknown): value is SortingState =>
  Array.isArray(value) &&
  value.every(
    (item) =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as { id?: unknown }).id === 'string' &&
      typeof (item as { desc?: unknown }).desc === 'boolean'
  );

const isColumnSizingState = (value: unknown): value is ColumnSizingState =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.values(value as Record<string, unknown>).every(
    (v) => typeof v === 'number' && Number.isFinite(v)
  );

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
  const data = useMemo(() => {
    if (portfolioContext?.isInitialized) return portfolioContext.positions;
    if (initialPositions?.length > 0) return initialPositions;
    return portfolioContext ? portfolioContext.positions : localPositions;
  }, [portfolioContext, initialPositions, localPositions]);

  const activeMetrics = useMemo(() => {
    if (portfolioContext?.isInitialized && portfolioContext.metrics) return portfolioContext.metrics;
    return _initialMetrics || portfolioContext?.metrics || null;
  }, [portfolioContext, _initialMetrics]);

  const setData = portfolioContext ? portfolioContext.setPositions : setLocalPositions;

  // Table & toolbar preferences
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>({});
  const [toolbarConfig, setToolbarConfig] = useState<ToolbarConfig>(DEFAULT_TOOLBAR_CONFIG);
  const [rowHeight, setRowHeight] = useState<number>(DEFAULT_ROW_HEIGHT);
  const [globalFilter, setGlobalFilter] = useState('');
  const [selectedExchange, setSelectedExchange] = useState<string>('ALL');
  const [selectedCurrency, setSelectedCurrency] = useState<string>('ALL');
  const [backupModalOpen, setBackupModalOpen] = useState(false);

  useEffect(() => {
    const savedSorting = getStoredJson<SortingState>(SORTING_STORAGE_KEY, [], isSortingState);
    if (savedSorting.length > 0) setSorting(savedSorting);
    const savedSizing = getStoredJson<ColumnSizingState>(COLUMN_SIZING_STORAGE_KEY, {}, isColumnSizingState);
    if (Object.keys(savedSizing).length > 0) setColumnSizing(savedSizing);
    const savedToolbar = getStoredJson<Partial<ToolbarConfig>>(TOOLBAR_STORAGE_KEY, {}, isPartialToolbarConfig);
    if (Object.keys(savedToolbar).length > 0) setToolbarConfig((prev) => ({ ...prev, ...savedToolbar }));
    const savedHeight = getStoredString(ROW_HEIGHT_STORAGE_KEY);
    if (savedHeight !== null) {
      const parsed = parseInt(savedHeight, 10);
      if (!Number.isNaN(parsed)) setRowHeight(clampRowHeight(parsed));
    }
  }, []);

  const handleSortingChange = useCallback((updater: React.SetStateAction<SortingState>) => {
    setSorting((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      setStoredJson(SORTING_STORAGE_KEY, next);
      return next;
    });
  }, []);

  const handleColumnSizingChange = useCallback((updater: React.SetStateAction<ColumnSizingState>) => {
    setColumnSizing((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (next && typeof next === 'object' && Object.keys(next).length > 0) {
        setStoredJson(COLUMN_SIZING_STORAGE_KEY, next);
      }
      return next;
    });
  }, []);

  const hasCustomColumnSizing = useMemo(() => Object.keys(columnSizing).length > 0, [columnSizing]);

  const handleRowHeightChange = useCallback((newHeight: number) => {
    const clamped = clampRowHeight(newHeight);
    setRowHeight(clamped);
    setStoredString(ROW_HEIGHT_STORAGE_KEY, String(clamped));
  }, []);

  const handleToggleToolbarAction = useCallback((key: keyof ToolbarConfig) => {
    setToolbarConfig((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      setStoredJson(TOOLBAR_STORAGE_KEY, next);
      return next;
    });
  }, []);

  const handleResetToolbarConfig = useCallback(() => {
    setToolbarConfig(DEFAULT_TOOLBAR_CONFIG);
    setRowHeight(DEFAULT_ROW_HEIGHT);
    removeStoredItem(TOOLBAR_STORAGE_KEY);
    removeStoredItem(ROW_HEIGHT_STORAGE_KEY);
    addToast('info', t('toolbarAndHeightResetToast'));
  }, [addToast, t]);

  const handleResetColumnWidths = useCallback(() => {
    setColumnSizing({});
    removeStoredItem(COLUMN_SIZING_STORAGE_KEY);
    addToast('info', t('columnWidthsResetToast'));
  }, [addToast, t]);

  const {
    batchRefreshing,
    refreshingTickers,
    wipeModalOpen,
    setWipeModalOpen,
    wipingDb,
    expandedDescriptionTickers,
    editingDateTicker,
    updatingDateTickers,
    handleStartEditingDate,
    handleCancelEditingDate,
    toggleDescription,
    reloadData,
    handleSaveComment,
    handleSaveDate,
    handleBatchRefresh,
    handleSingleRefresh,
    handleWipeDatabase,
  } = useWatchlistActions({
    data,
    setData,
    activeMetrics,
    portfolioContext,
    onDataChange,
    addToast,
    language,
    t,
  });

  const exchanges = useMemo(
    () => Array.from(new Set(data.map((p) => p.exchange).filter(Boolean))).sort(),
    [data]
  );
  const currencies = useMemo(
    () => Array.from(new Set(data.map((p) => p.currency).filter(Boolean))).sort(),
    [data]
  );
  const filteredData = useMemo(
    () =>
      filterWatchlistPositions(data, {
        exchange: selectedExchange,
        currency: selectedCurrency,
        query: globalFilter,
      }),
    [data, selectedExchange, selectedCurrency, globalFilter]
  );

  const columns = useMemo(
    () =>
      buildWatchlistColumns({
        editingDateTicker,
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
      }),
    [
      editingDateTicker,
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
    state: { sorting, columnSizing },
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
  const cellPaddingClass = useMemo(() => getRowCellPaddingClass(rowHeight), [rowHeight]);

  return (
    <div className="flex flex-col gap-4 relative">
      <WipeDatabaseModal
        open={wipeModalOpen}
        onClose={() => setWipeModalOpen(false)}
        onConfirm={handleWipeDatabase}
        loading={wipingDb}
      />

      <BackupExportModal
        isOpen={backupModalOpen}
        onClose={() => setBackupModalOpen(false)}
        onDataRestored={portfolioContext ? undefined : reloadData}
      />

      <WatchlistToolbar
        globalFilter={globalFilter}
        onGlobalFilterChange={setGlobalFilter}
        selectedExchange={selectedExchange}
        onSelectedExchangeChange={setSelectedExchange}
        exchanges={exchanges}
        selectedCurrency={selectedCurrency}
        onSelectedCurrencyChange={setSelectedCurrency}
        currencies={currencies}
        filteredCount={filteredData.length}
        totalCount={data.length}
        toolbarConfig={toolbarConfig}
        onToggleToolbarAction={handleToggleToolbarAction}
        onResetToolbarConfig={handleResetToolbarConfig}
        hasCustomColumnSizing={hasCustomColumnSizing}
        onResetColumnWidths={handleResetColumnWidths}
        rowHeight={rowHeight}
        onRowHeightChange={handleRowHeightChange}
        appConfig={appConfig}
        batchRefreshing={batchRefreshing}
        wipingDb={wipingDb}
        onBatchRefresh={handleBatchRefresh}
        onOpenBackupModal={() => setBackupModalOpen(true)}
        onOpenWipeModal={() => setWipeModalOpen(true)}
        onAddInstrument={onAddInstrument}
      />

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
                    headerSize < 75 ? 'py-2 px-1.5 pr-2' : headerSize < 100 ? 'py-2.5 px-2.5 pr-2.5' : 'py-3 px-3.5 pr-3';
                  const headerFontClass =
                    headerSize < 80 ? 'text-[9.5px] leading-[1.08]' : headerSize < 110 ? 'text-[11px] leading-tight' : 'text-xs leading-normal';
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      style={{ width: `${headerSize}px` }}
                      className={`${headerPaddingClass} ${headerFontClass} font-semibold text-zinc-400 relative select-none group/th align-middle`}
                    >
                      <div className="w-full [word-break:keep-all] whitespace-normal [overflow-wrap:normal]">
                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      </div>
                      {header.column.getCanResize() && (
                        <div
                          onMouseDown={header.getResizeHandler()}
                          onTouchStart={header.getResizeHandler()}
                          onDoubleClick={() => header.column.resetSize()}
                          onClick={(e) => e.stopPropagation()}
                          className={`absolute right-0 top-0 h-full w-2.5 cursor-col-resize select-none touch-none flex items-center justify-center transition-all group-hover/th:opacity-100 z-20 ${
                            header.column.getIsResizing() ? 'opacity-100' : 'opacity-0'
                          }`}
                          title={t('resizerTooltip')}
                        >
                          <div
                            className={`w-[2px] transition-all rounded-full ${
                              header.column.getIsResizing() ? 'bg-emerald-400 h-full shadow-[0_0_8px_rgba(52,211,153,0.9)]' : 'bg-zinc-600 hover:bg-emerald-400 h-4'
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
            const isExpanded = expandedDescriptionTickers.has(ticker);
            return (
              <tbody key={virtualRow.key} data-index={virtualRow.index} ref={rowVirtualizer.measureElement} className="font-sans">
                <tr
                  className={`group border-b border-zinc-800/60 transition-colors hover:bg-zinc-800/30 ${
                    refreshingTickers.has(ticker) ? 'opacity-60' : ''
                  } ${isExpanded ? 'bg-zinc-850/60' : ''}`}
                  style={{ height: `${rowHeight}px` }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={{ width: `${cell.column.getSize()}px`, height: `${rowHeight}px` }}
                      className={`${cellPaddingClass} ${cell.column.id === 'actions' ? '!px-1.5' : ''} align-middle overflow-hidden`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
                {isExpanded && (
                  <InstrumentDescriptionPanel
                    position={row.original}
                    colSpan={row.getVisibleCells().length}
                    onSave={handleSaveComment}
                    onClose={toggleDescription}
                  />
                )}
              </tbody>
            );
          })}
          <WatchlistRowSpacer height={bottomSpace} columnCount={columns.length} />
          <WatchlistEmptyState
            colSpan={columns.length}
            hasRows={rows.length > 0}
            totalDataCount={data.length}
            isUnauthenticatedEmpty={Boolean(isAuthConfigured && !user && data.length === 0)}
            isInitializing={Boolean(portfolioContext && !portfolioContext.isInitialized && data.length === 0)}
            onOpenAuthModal={() => openAuthModal()}
            onAddInstrument={onAddInstrument}
          />
        </table>
      </div>

      {batchRefreshing && (
        <div className="absolute inset-0 bg-zinc-950/20 rounded-xl flex items-center justify-center pointer-events-none z-10">
          <div className="flex items-center gap-3 bg-zinc-900/95 border border-zinc-700 rounded-xl px-5 py-3 shadow-2xl">
            <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none text-emerald-400" />
            <span className="text-sm text-zinc-200 font-medium">{t('updatingYahoo')}</span>
          </div>
        </div>
      )}
    </div>
  );
}
