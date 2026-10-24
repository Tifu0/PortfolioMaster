'use client';

// 'use client' is required because this interactive modal manages form state,
// tabs switching, validation, API submissions, and reactive callbacks.

import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  PlusCircle,
  Edit3,
  Trash2,
  RefreshCw,
  Loader2,
  Check,
  CalendarCheck,
  Search,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import type { Instrument, CheckYahooResponse } from '@/lib/types';
import {
  createInstrument,
  updateInstrument,
  deleteInstrument,
  refreshInstrument,
  getInstruments,
  getInstrument,
  fetchAnalysisPrice,
  fetchYtdPrice,
  checkYahooTicker,
} from '@/lib/api';
import { usePortfolioOptional } from '@/context/PortfolioContext';

const POPULAR_EXCHANGES: { label: string; value: string }[] = [
  { label: 'AUTO (Detección automática)', value: 'AUTO' },
  { label: 'Estados Unidos (US)', value: 'US' },
  { label: 'España — BME (SPAIN)', value: 'SPAIN' },
  { label: 'Francia — Euronext Paris (FRANCE)', value: 'FRANCE' },
  { label: 'Alemania — Xetra (GERMANY)', value: 'GERMANY' },
  { label: 'Reino Unido — LSE (UK)', value: 'UK' },
  { label: 'Italia — Borsa Italiana (ITALY)', value: 'ITALY' },
  { label: 'Países Bajos — Euronext Amsterdam (NETHERLANDS)', value: 'NETHERLANDS' },
  { label: 'Suiza — SIX (SWITZERLAND)', value: 'SWITZERLAND' },
  { label: 'Japón — Tokyo (JAPAN)', value: 'JAPAN' },
  { label: 'Hong Kong — HKEX (HONG_KONG)', value: 'HONG_KONG' },
];

const POPULAR_CURRENCIES: { label: string; value: string }[] = [
  { label: 'AUTO (Detección automática)', value: 'AUTO' },
  { label: 'EUR — Euro (€)', value: 'EUR' },
  { label: 'USD — Dólar estadounidense ($)', value: 'USD' },
  { label: 'GBP — Libra esterlina (£)', value: 'GBP' },
  { label: 'CHF — Franco suizo (CHF)', value: 'CHF' },
  { label: 'JPY — Yen japonés (¥)', value: 'JPY' },
  { label: 'CAD — Dólar canadiense (CAD)', value: 'CAD' },
  { label: 'AUD — Dólar australiano (AUD)', value: 'AUD' },
  { label: 'SEK — Corona sueca (SEK)', value: 'SEK' },
  { label: 'NOK — Corona noruega (NOK)', value: 'NOK' },
];

interface ManualEntryModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTickerToEdit?: string | null;
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
}

export function ManualEntryModal({
  isOpen,
  onClose,
  initialTickerToEdit,
  onSuccess,
  onError,
}: ManualEntryModalProps) {
  const portfolioContext = usePortfolioOptional();

  const isEditMode = Boolean(initialTickerToEdit);
  const [loading, setLoading] = useState(false);
  const [instrumentsList, setInstrumentsList] = useState<Instrument[]>([]);

  // ── Add Instrument Form State ────────────────────────────────────────── //
  const [addTicker, setAddTicker] = useState('');
  const [addCompanyName, setAddCompanyName] = useState('');
  const [addExchange, setAddExchange] = useState('AUTO');
  const [addCurrency, setAddCurrency] = useState('AUTO');
  const [addTargetPrice, setAddTargetPrice] = useState('');
  const [addAnalysisPrice, setAddAnalysisPrice] = useState('');
  const [addAnalysisDate, setAddAnalysisDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [addComment, setAddComment] = useState('');
  const [addFetchYahoo, setAddFetchYahoo] = useState(true);
  const [addManualPrice, setAddManualPrice] = useState('');
  const [addManualPrevClose, setAddManualPrevClose] = useState('');
  const [checkingAddYahoo, setCheckingAddYahoo] = useState(false);

  // ── Edit Instrument Form State ───────────────────────────────────────── //
  const [originalTickerToEdit, setOriginalTickerToEdit] = useState<string>('');
  const [editTicker, setEditTicker] = useState<string>('');
  const [editCompanyName, setEditCompanyName] = useState('');
  const [editExchange, setEditExchange] = useState('AUTO');
  const [editCurrency, setEditCurrency] = useState('AUTO');
  const [editTargetPrice, setEditTargetPrice] = useState('');
  const [editAnalysisPrice, setEditAnalysisPrice] = useState('');
  const [editAnalysisDate, setEditAnalysisDate] = useState('');
  const [editStartOfYearPrice, setEditStartOfYearPrice] = useState('');
  const [editStartOfYearDate, setEditStartOfYearDate] = useState('');
  const [editComment, setEditComment] = useState('');
  const [editLatestPrice, setEditLatestPrice] = useState('');
  const [editPrevClose, setEditPrevClose] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [fetchingHistorical, setFetchingHistorical] = useState(false);
  const [checkingYahoo, setCheckingYahoo] = useState(false);
  const [syncingTickerData, setSyncingTickerData] = useState(false);
  const [yahooCheckResult, setYahooCheckResult] = useState<CheckYahooResponse | null>(null);
  const [isAnalysisPriceManuallyEdited, setIsAnalysisPriceManuallyEdited] = useState(false);
  const [savingAction, setSavingAction] = useState<'standard' | 'with_date' | null>(null);

  // Helper to obtain today's date in local YYYY-MM-DD format
  const getTodayLocalDateString = (): string => {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const isSubmitting = loading || fetchingHistorical || checkingYahoo || syncingTickerData;

  // Load available instruments
  const loadInstruments = useCallback(async () => {
    try {
      const res = await getInstruments();
      setInstrumentsList(res.instruments || []);
    } catch {
      // Backend might be offline
    }
  }, []);

  // Handle Escape key to close modal
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Synchronize modal state and fetch instrument details whenever modal opens or ticker changes
  useEffect(() => {
    let ignore = false;
    if (!isOpen) {
      // Clean up modal state on close to guarantee zero stale cache on reopen
      void Promise.resolve().then(() => {
        if (ignore) return;
        setOriginalTickerToEdit('');
        setEditTicker('');
        setEditCompanyName('');
        setEditExchange('AUTO');
        setEditCurrency('AUTO');
        setEditTargetPrice('');
        setEditAnalysisPrice('');
        setEditAnalysisDate('');
        setEditStartOfYearPrice('');
        setEditStartOfYearDate('');
        setEditComment('');
        setEditLatestPrice('');
        setEditPrevClose('');
        setConfirmDelete(false);
        setYahooCheckResult(null);
        setIsAnalysisPriceManuallyEdited(false);
        setSavingAction(null);
      });
      return () => {
        ignore = true;
      };
    }

    let isMounted = true;
    void Promise.resolve().then(async () => {
      if (!isMounted) return;
      loadInstruments();
      setIsAnalysisPriceManuallyEdited(false);
      setSavingAction(null);

      const targetTicker = initialTickerToEdit;
      if (!targetTicker) {
        setOriginalTickerToEdit('');
        setEditTicker('');
        setConfirmDelete(false);
        setYahooCheckResult(null);
        return;
      }

      setOriginalTickerToEdit(targetTicker);
      setEditTicker(targetTicker);
      setYahooCheckResult(null);
      setConfirmDelete(false);

      try {
        const detail = await getInstrument(targetTicker);
        if (!isMounted) return;
        const inst = detail.instrument || (detail as unknown as Partial<Instrument>);
        const quote = detail.quote;

        setEditTicker(inst.user_ticker ? String(inst.user_ticker) : targetTicker);
        setEditCompanyName(inst.company_name ? String(inst.company_name) : '');
        setEditExchange(inst.exchange ? String(inst.exchange) : 'AUTO');
        setEditCurrency(inst.currency ? String(inst.currency) : 'AUTO');
        setEditTargetPrice(
          inst.target_price !== null && inst.target_price !== undefined
            ? String(inst.target_price)
            : ''
        );
        setEditAnalysisPrice(
          inst.analysis_reference_price !== null &&
          inst.analysis_reference_price !== undefined
            ? String(inst.analysis_reference_price)
            : ''
        );
        setEditAnalysisDate(inst.analysis_date ? String(inst.analysis_date) : '');
        setEditStartOfYearPrice(
          inst.start_of_year_price !== null &&
          inst.start_of_year_price !== undefined
            ? String(inst.start_of_year_price)
            : ''
        );
        setEditStartOfYearDate(inst.start_of_year_date ? String(inst.start_of_year_date) : '');
        setEditComment(inst.comment ? String(inst.comment) : '');
        setEditLatestPrice(
          quote?.price !== null && quote?.price !== undefined
            ? String(quote.price)
            : ''
        );
        setEditPrevClose(
          quote?.previous_close !== null && quote?.previous_close !== undefined
            ? String(quote.previous_close)
            : ''
        );
        setIsAnalysisPriceManuallyEdited(false);
        setConfirmDelete(false);
        setYahooCheckResult(null);
      } catch (err: unknown) {
        console.error('Error fetching instrument details:', err);
      }
    });

    return () => {
      isMounted = false;
    };
  }, [isOpen, initialTickerToEdit, loadInstruments]);

  if (!isOpen) return null;

  // ── Auto-Detect Company Name and Currency for Add ────────────────────── //
  const handleAutoDetectForAdd = async () => {
    const ticker = addTicker.trim();
    if (!ticker) {
      onError?.('Introduce un ticker primero para consultar en Yahoo Finance.');
      return;
    }
    setCheckingAddYahoo(true);
    try {
      const res = await checkYahooTicker(
        ticker,
        addCurrency === 'AUTO' ? undefined : addCurrency
      );
      if (res.available) {
        if (res.company_name) {
          setAddCompanyName(res.company_name);
        }
        if (res.currency) {
          setAddCurrency(res.currency);
        }
        if (res.price !== undefined && res.price !== null && !addManualPrice) {
          setAddManualPrice(String(res.price));
        }
        onSuccess?.(
          `Datos detectados de Yahoo: ${res.company_name || ticker} (${res.currency || ''})`
        );
      } else {
        onError?.(res.message || 'Yahoo Finance no encontró información para este ticker.');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al consultar Yahoo Finance: ${msg}`);
    } finally {
      setCheckingAddYahoo(false);
    }
  };

  // ── Submit Add Instrument ────────────────────────────────────────────── //
  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addTicker.trim()) {
      onError?.('El ticker es obligatorio (ej. AAPL, BME:SAN, MSFT).');
      return;
    }

    setLoading(true);
    try {
      await createInstrument({
        user_ticker: addTicker.trim(),
        company_name: addCompanyName.trim() || undefined,
        exchange: addExchange,
        currency: addCurrency.trim().toUpperCase(),
        target_price: addTargetPrice.trim() !== '' ? parseFloat(addTargetPrice) : null,
        analysis_reference_price: addAnalysisPrice.trim() !== '' ? parseFloat(addAnalysisPrice) : null,
        analysis_date: addAnalysisDate && addAnalysisDate.trim() ? addAnalysisDate.trim() : null,
        start_of_year_price: null,
        start_of_year_date: null,
        comment: addComment.trim(),
        fetch_yahoo: addFetchYahoo,
        manual_price: !addFetchYahoo && addManualPrice.trim() !== '' ? parseFloat(addManualPrice) : null,
        manual_previous_close:
          !addFetchYahoo && addManualPrevClose.trim() !== '' ? parseFloat(addManualPrevClose) : null,
      });

      onSuccess?.(`Instrumento ${addTicker.trim()} añadido con éxito.`);
      if (portfolioContext) {
        portfolioContext.refreshPortfolioData({ silent: true });
      }
      // Reset form
      setAddTicker('');
      setAddCompanyName('');
      setAddExchange('AUTO');
      setAddCurrency('AUTO');
      if (addTargetPrice) setAddTargetPrice('');
      if (addAnalysisPrice) setAddAnalysisPrice('');
      setAddComment('');
      setAddManualPrice('');
      setAddManualPrevClose('');
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al añadir instrumento: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  // ── Yahoo Availability Check for Edit Ticker ────────────────────────── //
  const handleCheckYahoo = async () => {
    const ticker = editTicker.trim();
    if (!ticker) {
      onError?.('Introduce un ticker para verificar en Yahoo Finance.');
      return;
    }
    setCheckingYahoo(true);
    setYahooCheckResult(null);
    try {
      const res = await checkYahooTicker(ticker);
      setYahooCheckResult(res);
      if (res.available) {
        onSuccess?.(
          `Ticker ${ticker} disponible en Yahoo Finance (${res.currency || ''} ${res.price ?? ''})`
        );
        if (res.price !== undefined && res.price !== null && !editLatestPrice) {
          setEditLatestPrice(String(res.price));
        }
        if (res.company_name && !editCompanyName) {
          setEditCompanyName(res.company_name);
        }
      } else {
        onError?.(res.message || `El ticker ${ticker} no parece estar disponible en Yahoo.`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al consultar Yahoo Finance: ${msg}`);
      setYahooCheckResult({
        available: false,
        message: msg,
      });
    } finally {
      setCheckingYahoo(false);
    }
  };

  // ── Explicit Confirm Ticker Change & Sync Metadata ───────────────────── //
  const handleConfirmTickerChange = async () => {
    const newTicker = editTicker.trim().toUpperCase();
    if (!newTicker) return;

    setSyncingTickerData(true);
    try {
      let checkData = yahooCheckResult;
      if (!checkData || !checkData.available || checkData.ticker?.toUpperCase() !== newTicker) {
        checkData = await checkYahooTicker(newTicker);
        setYahooCheckResult(checkData);
      }

      if (!checkData.available) {
        onError?.(checkData.message || `No se pudo obtener información para ${newTicker}`);
        return;
      }

      // 1. Overwrite company name, exchange, currency, live prices
      if (checkData.company_name) {
        setEditCompanyName(checkData.company_name);
      } else {
        setEditCompanyName(newTicker);
      }
      if (checkData.currency) {
        setEditCurrency(checkData.currency);
      }
      if (checkData.exchange) {
        setEditExchange(checkData.exchange);
      }
      if (checkData.price !== undefined && checkData.price !== null) {
        setEditLatestPrice(String(checkData.price));
      }
      if (checkData.previous_close !== undefined && checkData.previous_close !== null) {
        setEditPrevClose(String(checkData.previous_close));
      }

      // 2. Clear stale reference prices and fetch fresh ones for the new ticker
      setEditAnalysisPrice('');
      setEditStartOfYearPrice('');

      const targetDate = editAnalysisDate || new Date().toISOString().split('T')[0];
      const [analysisRes, ytdRes] = await Promise.allSettled([
        fetchAnalysisPrice(newTicker, targetDate),
        fetchYtdPrice(newTicker),
      ]);

      if (analysisRes.status === 'fulfilled' && analysisRes.value.status === 'ok') {
        setEditAnalysisPrice(String(analysisRes.value.analysis_reference_price));
        if (analysisRes.value.analysis_date) {
          setEditAnalysisDate(analysisRes.value.analysis_date);
        }
      }

      if (ytdRes.status === 'fulfilled' && ytdRes.value.status === 'ok') {
        setEditStartOfYearPrice(String(ytdRes.value.start_of_year_price));
        if (ytdRes.value.start_of_year_date) {
          setEditStartOfYearDate(ytdRes.value.start_of_year_date);
        }
      }

      setIsAnalysisPriceManuallyEdited(false);
      onSuccess?.(`Datos y precios de ${newTicker} sincronizados correctamente.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al sincronizar datos del ticker: ${msg}`);
    } finally {
      setSyncingTickerData(false);
    }
  };

  // ── Unified Save Handler for Edit Mode (DRY & Zero Network Overhead) ──── //
  const handleSave = async (updateDateToToday: boolean = false) => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;

    const trimmedNewTicker = editTicker.trim().toUpperCase();
    if (!trimmedNewTicker) {
      onError?.('El ticker no puede estar vacío.');
      return;
    }

    setLoading(true);
    setSavingAction(updateDateToToday ? 'with_date' : 'standard');
    try {
      let resolvedAnalysisDate = editAnalysisDate || null;
      let resolvedAnalysisPrice =
        editAnalysisPrice.trim() !== '' ? parseFloat(editAnalysisPrice) : null;

      if (updateDateToToday) {
        resolvedAnalysisDate = getTodayLocalDateString();
        if (isAnalysisPriceManuallyEdited) {
          resolvedAnalysisPrice =
            editAnalysisPrice.trim() !== '' ? parseFloat(editAnalysisPrice) : null;
        } else if (
          editLatestPrice.trim() !== '' &&
          !isNaN(parseFloat(editLatestPrice))
        ) {
          resolvedAnalysisPrice = parseFloat(editLatestPrice);
        }
      }

      const payload: Parameters<typeof updateInstrument>[1] = {
        company_name: editCompanyName.trim() !== '' ? editCompanyName.trim() : null,
        exchange: editExchange !== 'AUTO' && editExchange.trim() !== '' ? editExchange : null,
        currency: editCurrency !== 'AUTO' && editCurrency.trim() !== '' ? editCurrency : null,
        target_price: editTargetPrice.trim() !== '' ? parseFloat(editTargetPrice) : null,
        analysis_reference_price: resolvedAnalysisPrice,
        analysis_date: resolvedAnalysisDate ? (typeof resolvedAnalysisDate === 'string' ? resolvedAnalysisDate.trim() : resolvedAnalysisDate) : null,
        start_of_year_price: editStartOfYearPrice.trim() !== '' ? parseFloat(editStartOfYearPrice) : null,
        start_of_year_date: editStartOfYearDate.trim() !== '' ? editStartOfYearDate.trim() : null,
        comment: editComment.trim() !== '' ? editComment.trim() : null,
        latest_price: editLatestPrice.trim() !== '' ? parseFloat(editLatestPrice) : null,
        previous_close: editPrevClose.trim() !== '' ? parseFloat(editPrevClose) : null,
      };

      if (trimmedNewTicker !== targetTicker.toUpperCase()) {
        payload.new_ticker = trimmedNewTicker;
      }

      await updateInstrument(targetTicker, payload);

      if (portfolioContext) {
        portfolioContext.optimisticUpdatePosition(targetTicker, {
          analysis_date: resolvedAnalysisDate,
          analysis_reference_price: resolvedAnalysisPrice,
          target_price: payload.target_price,
          comment: payload.comment || '',
        });
        await portfolioContext.refreshPortfolioData({ silent: true });
      }

      onSuccess?.(
        updateDateToToday
          ? `Instrumento ${trimmedNewTicker} actualizado con fecha de hoy.`
          : `Instrumento ${trimmedNewTicker} actualizado correctamente.`
      );
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al actualizar instrumento: ${msg}`);
    } finally {
      setLoading(false);
      setSavingAction(null);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await handleSave(false);
  };

  // ── Fetch historical quote for analysis date ───────────────────────── //
  const handleFetchHistoricalForEdit = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setFetchingHistorical(true);
    try {
      const res = await fetchAnalysisPrice(targetTicker, editAnalysisDate || undefined);
      if (res.status === 'ok') {
        setEditAnalysisPrice(String(res.analysis_reference_price));
        if (res.analysis_date) setEditAnalysisDate(res.analysis_date);
        setIsAnalysisPriceManuallyEdited(false);
        onSuccess?.(`Cotización en fecha de análisis obtenida de Yahoo: ${res.analysis_reference_price}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al consultar Yahoo Finance: ${msg}`);
    } finally {
      setFetchingHistorical(false);
    }
  };

  const handleFetchYtdForEdit = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setFetchingHistorical(true);
    try {
      const res = await fetchYtdPrice(targetTicker);
      if (res.status === 'ok') {
        setEditStartOfYearPrice(String(res.start_of_year_price));
        if (res.start_of_year_date) setEditStartOfYearDate(res.start_of_year_date);
        onSuccess?.(`Cotización inicio de año (YTD) obtenida de Yahoo: ${res.start_of_year_price}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al consultar Yahoo Finance: ${msg}`);
    } finally {
      setFetchingHistorical(false);
    }
  };


  // ── Refresh Quote Now for Edited Instrument ─────────────────────────── //
  const handleSingleYahooRefresh = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setLoading(true);
    try {
      const res = await refreshInstrument(targetTicker);
      if (res.status === 'ok') {
        onSuccess?.(`${targetTicker}: cotización actualizada desde Yahoo Finance.`);
        if (res.price !== undefined && res.price !== null) {
          setEditLatestPrice(String(res.price));
        }
        if (res.previous_close !== undefined && res.previous_close !== null) {
          setEditPrevClose(String(res.previous_close));
        }
        if (portfolioContext) {
          portfolioContext.refreshPortfolioData({ silent: true });
        }
      } else {
        onError?.(`${targetTicker}: ${res.detail || 'sin datos disponibles'}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al consultar Yahoo Finance: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  // ── Delete Instrument (Optimistic UI with Rollback) ─────────────────── //
  const handleDeleteInstrument = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setLoading(true);

    // Instant optimistic deletion from UI
    const rollback = portfolioContext?.optimisticDelete(targetTicker);

    try {
      await deleteInstrument(targetTicker);
      onSuccess?.(`Instrumento ${targetTicker} eliminado de la base de datos.`);
      if (portfolioContext) {
        portfolioContext.refreshPortfolioData({ silent: true });
      }
      onClose();
    } catch (err: unknown) {
      // Rollback to previous positions if delete failed
      rollback?.();
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al eliminar instrumento: ${msg}`);
    } finally {
      setLoading(false);
      setConfirmDelete(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-2xl bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-zinc-950/60">
          <div className="flex items-center gap-3">
            <div
              className={`w-8 h-8 rounded-lg border flex items-center justify-center ${
                isEditMode
                  ? 'bg-blue-500/10 border-blue-500/20 text-blue-400'
                  : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              }`}
            >
              {isEditMode ? <Edit3 className="w-4 h-4" /> : <PlusCircle className="w-4 h-4" />}
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-tight">
                {isEditMode
                  ? `Modificar Instrumento (${originalTickerToEdit || editTicker})`
                  : 'Añadir Nuevo Instrumento'}
              </h2>
              <p className="text-xs text-zinc-400">
                {isEditMode
                  ? 'Edita los datos del valor, actualiza su cotización o elimínalo del watchlist'
                  : 'Introduce los datos del nuevo valor para añadirlo a tu watchlist'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Cerrar modal"
            title="Cerrar modal"
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="overflow-y-auto p-6 space-y-6 flex-1">
          {!isEditMode ? (
            /* ──────────────────────────────────────────────────────────── */
            /* ADD NEW INSTRUMENT                                          */
            /* ──────────────────────────────────────────────────────────── */
            <form onSubmit={handleAddSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* User Ticker */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs font-medium text-zinc-300">
                      Ticker <span className="text-rose-400">*</span>
                    </label>
                    <button
                      type="button"
                      onClick={handleAutoDetectForAdd}
                      disabled={checkingAddYahoo || !addTicker.trim()}
                      className="inline-flex items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300 disabled:opacity-40 disabled:hover:text-emerald-400 transition font-medium"
                      title="Consultar Yahoo Finance para autocompletar nombre y divisa"
                    >
                      {checkingAddYahoo ? (
                        <>
                          <Loader2 className="w-3 h-3 animate-spin" />
                          Consultando...
                        </>
                      ) : (
                        <>
                          <Search className="w-3 h-3" />
                          Consultar en Yahoo
                        </>
                      )}
                    </button>
                  </div>
                  <input
                    type="text"
                    required
                    placeholder="ej. AAPL, BME:SAN, MSFT"
                    value={addTicker}
                    onChange={(e) => setAddTicker(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60 font-mono uppercase"
                  />
                  <span className="text-[10px] text-zinc-500 mt-1 block">
                    Soporta prefijos como <code className="text-zinc-400">BME:</code>,{' '}
                    <code className="text-zinc-400">NASDAQ:</code>
                  </span>
                </div>

                {/* Company Name */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs font-medium text-zinc-300">
                      Nombre de la Empresa
                    </label>
                    <button
                      type="button"
                      onClick={() =>
                        setAddCompanyName(
                          addCompanyName === 'AUTO' || !addCompanyName ? '' : 'AUTO'
                        )
                      }
                      className={`text-[10px] font-medium px-2 py-0.5 rounded-md border transition-colors ${
                        addCompanyName === 'AUTO' || !addCompanyName
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                          : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-zinc-200'
                      }`}
                      title="Activar detección automática desde Yahoo Finance"
                    >
                      {addCompanyName === 'AUTO' || !addCompanyName
                        ? '✓ Modo AUTO'
                        : 'Poner en AUTO'}
                    </button>
                  </div>
                  <input
                    type="text"
                    placeholder="ej. Apple Inc. (o deja 'AUTO' para Yahoo)"
                    value={addCompanyName}
                    onChange={(e) => setAddCompanyName(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60"
                  />
                  <span className="text-[10px] text-zinc-500 mt-1 block">
                    Si se deja vacío o en <code className="text-zinc-400">AUTO</code>, se obtendrá de Yahoo Finance.
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Exchange */}
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Mercado / Bolsa
                  </label>
                  <select
                    value={addExchange}
                    onChange={(e) => setAddExchange(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60"
                  >
                    {POPULAR_EXCHANGES.map((ex) => (
                      <option key={ex.value} value={ex.value} className="bg-zinc-900">
                        {ex.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Currency */}
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">Divisa</label>
                  <select
                    value={addCurrency}
                    onChange={(e) => setAddCurrency(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                  >
                    {POPULAR_CURRENCIES.map((curr) => (
                      <option key={curr.value} value={curr.value} className="bg-zinc-900">
                        {curr.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Price Targets */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Precio Objetivo
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="ej. 240.00"
                    value={addTargetPrice}
                    onChange={(e) => setAddTargetPrice(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Fecha de Análisis
                  </label>
                  <input
                    type="date"
                    value={addAnalysisDate}
                    onChange={(e) => setAddAnalysisDate(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                  />
                  <span className="text-[10px] text-zinc-500 mt-1 block">
                    La cotización de referencia en esta fecha se resolverá automáticamente de Yahoo Finance.
                  </span>
                </div>
              </div>

              {/* Comment / Thesis */}
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1">
                  Comentario / Tesis de Inversión
                </label>
                <textarea
                  rows={2}
                  placeholder="ej. Crecimiento sostenido en servicios y recompras de acciones."
                  value={addComment}
                  onChange={(e) => setAddComment(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60 resize-none"
                />
              </div>

              {/* Quote Source Toggle */}
              <div className="pt-2 border-t border-zinc-800/80">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-zinc-300">
                    Fuente de la Cotización Inicial
                  </span>
                  <label className="inline-flex items-center gap-2 cursor-pointer text-xs text-zinc-400">
                    <input
                      type="checkbox"
                      checked={addFetchYahoo}
                      onChange={(e) => setAddFetchYahoo(e.target.checked)}
                      className="rounded bg-zinc-950 border-zinc-700 text-emerald-500 focus:ring-emerald-500/20"
                    />
                    Consultar Yahoo Finance automáticamente
                  </label>
                </div>

                {!addFetchYahoo && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3 rounded-xl bg-zinc-950/60 border border-zinc-800">
                    <div>
                      <label className="block text-xs font-medium text-zinc-300 mb-1">
                        Último Precio Manual
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        placeholder="ej. 175.50"
                        value={addManualPrice}
                        onChange={(e) => setAddManualPrice(e.target.value)}
                        className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-200 font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-zinc-300 mb-1">
                        Cierre Anterior Manual
                      </label>
                      <input
                        type="number"
                        step="0.01"
                        placeholder="ej. 174.20"
                        value={addManualPrevClose}
                        onChange={(e) => setAddManualPrevClose(e.target.value)}
                        className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-200 font-mono"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Submit Button */}
              <div className="pt-4 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors disabled:opacity-50 shadow-lg shadow-emerald-950/40"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Guardando...
                    </>
                  ) : (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      Guardar Instrumento
                    </>
                  )}
                </button>
              </div>
            </form>
          ) : (
            /* ──────────────────────────────────────────────────────────── */
            /* TAB B: EDIT OR DELETE EXISTING INSTRUMENT                    */
            /* ──────────────────────────────────────────────────────────── */
            <div className="space-y-5">
              {!originalTickerToEdit && instrumentsList.length === 0 ? (
                <div className="p-8 text-center text-zinc-400 text-xs">
                  No hay instrumentos registrados todavía en la base de datos.
                </div>
              ) : (
                <>
                  {/* Ticker Input Field & Yahoo Finance Availability Check */}
                  <div className="bg-zinc-900/60 p-3.5 rounded-xl border border-zinc-800/80 space-y-2.5">
                    <div className="flex items-center justify-between">
                      <label className="block text-xs font-medium text-zinc-300">
                        Ticker del Instrumento
                      </label>
                      {originalTickerToEdit && editTicker.trim().toUpperCase() !== originalTickerToEdit.toUpperCase() && (
                        <span className="text-[10px] text-amber-400 font-medium">
                          Cambiando ticker original ({originalTickerToEdit})
                        </span>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <div className="relative flex-1">
                        <input
                          type="text"
                          value={editTicker}
                          onChange={(e) => {
                            setEditTicker(e.target.value.toUpperCase());
                            setYahooCheckResult(null);
                          }}
                          placeholder="ej. AAPL, MC.PA, SAN.MC..."
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-100 font-mono font-semibold tracking-wide focus:outline-none focus:border-emerald-500/60 uppercase"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={handleCheckYahoo}
                        disabled={checkingYahoo || !editTicker.trim()}
                        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-50 transition-colors whitespace-nowrap"
                        title="Comprobar disponibilidad del ticker en Yahoo Finance"
                      >
                        {checkingYahoo ? (
                          <>
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Comprobando...
                          </>
                        ) : (
                          <>
                            <Search className="w-3.5 h-3.5" />
                            Comprobar en Yahoo
                          </>
                        )}
                      </button>
                    </div>

                    {/* Result banner from Yahoo check */}
                    {yahooCheckResult && (
                      <div
                        className={`flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3 rounded-xl text-xs ${
                          yahooCheckResult.available
                            ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                            : 'bg-rose-500/10 border border-rose-500/20 text-rose-300'
                        }`}
                      >
                        <div className="flex items-start gap-2.5">
                          {yahooCheckResult.available ? (
                            <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                          ) : (
                            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                          )}
                          <div>
                            {yahooCheckResult.available ? (
                              <div>
                                <p className="font-semibold text-emerald-200">
                                  Ticker válido y disponible en Yahoo Finance
                                </p>
                                <p className="text-[11px] text-emerald-400/80 mt-0.5 font-mono">
                                  Símbolo: {yahooCheckResult.provider_symbol}
                                  {yahooCheckResult.company_name ? ` · ${yahooCheckResult.company_name}` : ''}
                                  {yahooCheckResult.price !== undefined && yahooCheckResult.price !== null
                                    ? ` · ${yahooCheckResult.price} ${yahooCheckResult.currency || ''}`
                                    : ''}
                                </p>
                              </div>
                            ) : (
                              <div>
                                <p className="font-medium text-rose-200">
                                  No se pudo encontrar en Yahoo Finance
                                </p>
                                <p className="text-[11px] text-rose-400/80 mt-0.5">
                                  {yahooCheckResult.message || 'Verifica el símbolo o el sufijo de bolsa (.MC, .PA, etc.)'}
                                </p>
                              </div>
                            )}
                          </div>
                        </div>

                        {yahooCheckResult.available && editTicker.trim().toUpperCase() !== originalTickerToEdit.toUpperCase() && (
                          <button
                            type="button"
                            onClick={handleConfirmTickerChange}
                            disabled={syncingTickerData || loading}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-sm disabled:opacity-50 whitespace-nowrap self-end sm:self-auto cursor-pointer"
                            title="Sobrescribir los datos y precios del formulario con los del nuevo ticker"
                          >
                            {syncingTickerData ? (
                              <>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                Actualizando...
                              </>
                            ) : (
                              <>
                                <RefreshCw className="w-3.5 h-3.5" />
                                Confirmar cambio y actualizar datos
                              </>
                            )}
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  <form onSubmit={handleEditSubmit} className="space-y-4">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-zinc-300 mb-1">
                          Nombre de la Empresa
                        </label>
                        <input
                          type="text"
                          value={editCompanyName}
                          onChange={(e) => setEditCompanyName(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-300 mb-1">
                          Precio Objetivo
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={editTargetPrice}
                          onChange={(e) => setEditTargetPrice(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="block text-xs font-medium text-zinc-300">
                            Precio Ref. Análisis
                          </label>
                          <button
                            type="button"
                            onClick={handleFetchHistoricalForEdit}
                            disabled={fetchingHistorical || loading}
                            className="text-[10px] text-emerald-400 hover:text-emerald-300 underline font-mono"
                            title="Consultar cotización de la fecha en Yahoo"
                          >
                            {fetchingHistorical ? 'Buscando...' : 'Obtener de Yahoo'}
                          </button>
                        </div>
                        <input
                          type="number"
                          step="0.01"
                          value={editAnalysisPrice}
                          onChange={(e) => {
                            setIsAnalysisPriceManuallyEdited(true);
                            setEditAnalysisPrice(e.target.value);
                          }}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-300 mb-1">
                          Fecha de Análisis
                        </label>
                        <input
                          type="date"
                          value={editAnalysisDate}
                          onChange={(e) => setEditAnalysisDate(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-300 mb-1">
                          Último Precio
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={editLatestPrice}
                          onChange={(e) => setEditLatestPrice(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-300 mb-1">
                          Cierre Anterior
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={editPrevClose}
                          onChange={(e) => setEditPrevClose(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="block text-xs font-medium text-zinc-300">
                            Precio Ref. YTD (Inicio Año)
                          </label>
                          <button
                            type="button"
                            onClick={handleFetchYtdForEdit}
                            disabled={fetchingHistorical || loading}
                            className="text-[10px] text-emerald-400 hover:text-emerald-300 underline font-mono"
                            title="Consultar cotización a inicio de año en Yahoo"
                          >
                            {fetchingHistorical ? 'Buscando...' : 'Obtener de Yahoo'}
                          </button>
                        </div>
                        <input
                          type="number"
                          step="0.01"
                          value={editStartOfYearPrice}
                          onChange={(e) => setEditStartOfYearPrice(e.target.value)}
                          placeholder="ej. 150.25"
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-zinc-300 mb-1">
                          Fecha YTD
                        </label>
                        <input
                          type="date"
                          value={editStartOfYearDate}
                          onChange={(e) => setEditStartOfYearDate(e.target.value)}
                          className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-zinc-300 mb-1">
                        Comentario
                      </label>
                      <textarea
                        rows={2}
                        value={editComment}
                        onChange={(e) => setEditComment(e.target.value)}
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 resize-none"
                      />
                    </div>

                    <div className="pt-3 border-t border-zinc-800 flex items-center justify-between gap-2">
                      {/* Yahoo quick fetch */}
                      <button
                        type="button"
                        onClick={handleSingleYahooRefresh}
                        disabled={isSubmitting}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shrink-0 whitespace-nowrap"
                        title="Consultar cotización en Yahoo Finance ahora"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                        <span className="hidden sm:inline">Consultar </span>Yahoo
                      </button>

                      <div className="flex items-center justify-end gap-2 ml-auto shrink-0">
                        <button
                          type="button"
                          onClick={onClose}
                          disabled={isSubmitting}
                          className="px-3 py-1.5 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors disabled:opacity-50 cursor-pointer whitespace-nowrap"
                        >
                          Cancelar
                        </button>
                        <button
                          type="submit"
                          disabled={isSubmitting}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/20 hover:border-emerald-500/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer whitespace-nowrap"
                          title="Guardar todos los cambios sin modificar la fecha de análisis"
                        >
                          {savingAction === 'standard' ? (
                            <>
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              Guardando...
                            </>
                          ) : (
                            <>
                              <Check className="w-3.5 h-3.5" />
                              Guardar Cambios
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleSave(true)}
                          disabled={isSubmitting}
                          className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 shadow-sm shadow-emerald-950/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer whitespace-nowrap"
                          title="Guardar cambios y actualizar la fecha de análisis a la fecha de hoy"
                        >
                          {savingAction === 'with_date' ? (
                            <>
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              Actualizando...
                            </>
                          ) : (
                            <>
                              <CalendarCheck className="w-3.5 h-3.5" />
                              Guardar + Actualizar Fecha
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </form>

                  {/* Danger Zone: Delete Instrument */}
                  <div className="mt-6 pt-4 border-t border-rose-500/20 bg-rose-500/[0.02] p-4 rounded-xl border">
                    <div className="flex items-center justify-between">
                      <div>
                        <h4 className="text-xs font-semibold text-rose-400 flex items-center gap-1.5">
                          <Trash2 className="w-3.5 h-3.5" />
                          Eliminar Instrumento
                        </h4>
                        <p className="text-[11px] text-zinc-500 mt-0.5">
                          Elimina <strong className="text-zinc-300">{originalTickerToEdit || editTicker}</strong> y todas sus cotizaciones asociadas.
                        </p>
                      </div>

                      {confirmDelete ? (
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setConfirmDelete(false)}
                            className="px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200"
                          >
                            Cancelar
                          </button>
                          <button
                            type="button"
                            onClick={handleDeleteInstrument}
                            disabled={loading}
                            className="px-3 py-1.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 rounded-lg transition-colors flex items-center gap-1.5"
                          >
                            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                            Confirmar Eliminación
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(true)}
                          className="px-3 py-1.5 text-xs font-medium text-rose-400 border border-rose-500/30 rounded-lg hover:bg-rose-500/10 transition-colors"
                        >
                          Eliminar
                        </button>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
