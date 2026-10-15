'use client';

// 'use client' is required here because WatchlistContent coordinates shared
// reactive state between MetricCards, WatchlistTable, and ManualEntryModal.
// It also reads query parameters (?add=1 or ?edit=TICKER) to control modal visibility.

import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import type { Position, PortfolioMetrics } from '@/lib/types';
import { MetricCards } from '@/components/MetricCards';
import { WatchlistTable } from '@/components/WatchlistTable';
import { ManualEntryModal } from '@/components/ManualEntryModal';
import { getPositions, getMetrics } from '@/lib/api';
import { Check, AlertTriangle, Info, X } from 'lucide-react';

interface WatchlistContentProps {
  initialPositions: Position[];
  initialMetrics: PortfolioMetrics | null;
}

interface ToastData {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

function ToastItem({ toast, onDismiss }: { toast: ToastData; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 5000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const styles = {
    success: 'bg-emerald-950/90 border-emerald-500/30 text-emerald-200',
    error: 'bg-rose-950/90 border-rose-500/30 text-rose-200',
    info: 'bg-blue-950/90 border-blue-500/30 text-blue-200',
  };

  const icons = {
    success: <Check className="w-4 h-4 text-emerald-400 shrink-0" />,
    error: <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />,
    info: <Info className="w-4 h-4 text-blue-400 shrink-0" />,
  };

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-xs shadow-2xl backdrop-blur-md transition-all animate-in slide-in-from-top-2 ${styles[toast.type]}`}
    >
      {icons[toast.type]}
      <span className="flex-1 font-medium">{toast.message}</span>
      <button
        onClick={onDismiss}
        className="text-zinc-400 hover:text-zinc-200 p-1 rounded transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

/**
 * WatchlistContent: Client coordinator for MetricCards, WatchlistTable,
 * ManualEntryModal, and reactive state updates.
 */
export function WatchlistContent({ initialPositions, initialMetrics }: WatchlistContentProps) {
  const [positions, setPositions] = useState<Position[]>(initialPositions);
  const [metrics, setMetrics] = useState<PortfolioMetrics | null>(initialMetrics);

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [tickerToEdit, setTickerToEdit] = useState<string | null>(null);

  // Toasts
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const toastIdRef = React.useRef(0);

  const router = useRouter();
  const searchParams = useSearchParams();

  const addToast = useCallback((type: ToastData['type'], message: string) => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, type, message }]);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Listen for ?add=1 or ?edit=TICKER in URL
  useEffect(() => {
    const addParam = searchParams.get('add');
    const editParam = searchParams.get('edit');

    if (addParam === '1' || addParam === 'true') {
      setTickerToEdit(null);
      setIsModalOpen(true);
    } else if (editParam) {
      setTickerToEdit(editParam);
      setIsModalOpen(true);
    }
  }, [searchParams]);

  // Reload data from API
  const reloadData = useCallback(async () => {
    try {
      const [posRes, metRes] = await Promise.allSettled([getPositions(), getMetrics()]);
      let newPos: Position[] = [];
      let newMet: PortfolioMetrics | null = null;

      if (posRes.status === 'fulfilled') {
        newPos = posRes.value.positions || [];
      }
      if (metRes.status === 'fulfilled') {
        newMet = metRes.value;
      }

      setPositions(newPos);
      setMetrics(newMet);
    } catch (err: unknown) {
      console.error('Error reloading portfolio data:', err);
    }
  }, []);

  const handleDataChange = useCallback(
    (newPositions: Position[], newMetrics: PortfolioMetrics | null) => {
      setPositions(newPositions);
      setMetrics(newMetrics);
    },
    []
  );

  const handleOpenAdd = useCallback(() => {
    setTickerToEdit(null);
    setIsModalOpen(true);
  }, []);

  const handleOpenEdit = useCallback((ticker: string) => {
    setTickerToEdit(ticker);
    setIsModalOpen(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setIsModalOpen(false);
    setTickerToEdit(null);
    // Clean URL query params without full reload
    if (searchParams.has('add') || searchParams.has('edit')) {
      router.replace('/', { scroll: false });
    }
  }, [router, searchParams]);

  const handleModalSuccess = useCallback(
    async (message: string) => {
      addToast('success', message);
      await reloadData();
    },
    [addToast, reloadData]
  );

  const handleModalError = useCallback(
    (message: string) => {
      addToast('error', message);
    },
    [addToast]
  );

  return (
    <>
      {/* Toast Notification Container */}
      {toasts.length > 0 && (
        <div className="fixed top-20 right-4 z-[200] flex flex-col gap-2 max-w-sm w-full pointer-events-auto">
          {toasts.map((t) => (
            <ToastItem key={t.id} toast={t} onDismiss={() => dismissToast(t.id)} />
          ))}
        </div>
      )}

      {/* Phase 4: Metric Cards */}
      <MetricCards metrics={metrics} positions={positions} />

      {/* Phase 3+6+7: Interactive Watchlist Table */}
      <WatchlistTable
        initialPositions={positions}
        initialMetrics={metrics}
        onDataChange={handleDataChange}
        onEditTicker={handleOpenEdit}
        onAddInstrument={handleOpenAdd}
      />

      {/* Phase 7: Manual Entry / Edit Modal (Tab 2) */}
      <ManualEntryModal
        isOpen={isModalOpen}
        onClose={handleCloseModal}
        initialTickerToEdit={tickerToEdit}
        onSuccess={handleModalSuccess}
        onError={handleModalError}
      />
    </>
  );
}
