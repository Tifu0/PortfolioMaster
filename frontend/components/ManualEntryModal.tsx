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
  AlertTriangle,
  Building,
  DollarSign,
  Calendar,
  FileText,
  Target,
  Search,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import type { Position, Instrument, Exchange, CheckYahooResponse } from '@/lib/types';
import {
  createInstrument,
  updateInstrument,
  deleteInstrument,
  refreshInstrument,
  getInstruments,
  getInstrument,
  fetchAnalysisPrice,
  checkYahooTicker,
} from '@/lib/api';

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
  const [editTargetPrice, setEditTargetPrice] = useState('');
  const [editAnalysisPrice, setEditAnalysisPrice] = useState('');
  const [editAnalysisDate, setEditAnalysisDate] = useState('');
  const [editComment, setEditComment] = useState('');
  const [editLatestPrice, setEditLatestPrice] = useState('');
  const [editPrevClose, setEditPrevClose] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [fetchingHistorical, setFetchingHistorical] = useState(false);
  const [checkingYahoo, setCheckingYahoo] = useState(false);
  const [yahooCheckResult, setYahooCheckResult] = useState<CheckYahooResponse | null>(null);

  // Load available instruments
  const loadInstruments = useCallback(async () => {
    try {
      const res = await getInstruments();
      setInstrumentsList(res.instruments || []);
    } catch {
      // Backend might be offline
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadInstruments();
      if (initialTickerToEdit) {
        setOriginalTickerToEdit(initialTickerToEdit);
        setEditTicker(initialTickerToEdit);
        setYahooCheckResult(null);
        setConfirmDelete(false);
      } else {
        setOriginalTickerToEdit('');
        setEditTicker('');
        setConfirmDelete(false);
        setYahooCheckResult(null);
      }
    }
  }, [isOpen, initialTickerToEdit, loadInstruments]);

  // When originalTickerToEdit changes, fetch details
  useEffect(() => {
    if (!originalTickerToEdit) return;
    let isMounted = true;
    (async () => {
      try {
        const detail = await getInstrument(originalTickerToEdit);
        if (!isMounted) return;
        const inst = (detail as any).instrument || detail;
        const quote = (detail as any).quote || detail.quote;

        setEditTicker(inst.user_ticker || originalTickerToEdit);
        setEditCompanyName(inst.company_name || '');
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
        setEditAnalysisDate(inst.analysis_date || '');
        setEditComment(inst.comment || '');
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
        setConfirmDelete(false);
        setYahooCheckResult(null);
      } catch (err: unknown) {
        console.error('Error fetching instrument details:', err);
      }
    })();
    return () => {
      isMounted = false;
    };
  }, [originalTickerToEdit]);

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
        target_price: addTargetPrice ? parseFloat(addTargetPrice) : null,
        analysis_reference_price: addAnalysisPrice ? parseFloat(addAnalysisPrice) : null,
        analysis_date: addAnalysisDate || null,
        comment: addComment.trim(),
        fetch_yahoo: addFetchYahoo,
        manual_price: !addFetchYahoo && addManualPrice ? parseFloat(addManualPrice) : null,
        manual_previous_close:
          !addFetchYahoo && addManualPrevClose ? parseFloat(addManualPrevClose) : null,
      });

      onSuccess?.(`Instrumento ${addTicker.trim()} añadido con éxito.`);
      // Reset form
      setAddTicker('');
      setAddCompanyName('');
      setAddExchange('AUTO');
      setAddCurrency('AUTO');
      addTargetPrice && setAddTargetPrice('');
      addAnalysisPrice && setAddAnalysisPrice('');
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

  // ── Submit Edit Instrument ───────────────────────────────────────────── //
  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;

    const trimmedNewTicker = editTicker.trim().toUpperCase();
    if (!trimmedNewTicker) {
      onError?.('El ticker no puede estar vacío.');
      return;
    }

    setLoading(true);
    try {
      const payload: Parameters<typeof updateInstrument>[1] = {
        company_name: editCompanyName.trim() || null,
        target_price: editTargetPrice ? parseFloat(editTargetPrice) : null,
        analysis_reference_price: editAnalysisPrice ? parseFloat(editAnalysisPrice) : null,
        analysis_date: editAnalysisDate || null,
        comment: editComment.trim() || null,
        latest_price: editLatestPrice ? parseFloat(editLatestPrice) : null,
        previous_close: editPrevClose ? parseFloat(editPrevClose) : null,
      };

      if (trimmedNewTicker !== targetTicker.toUpperCase()) {
        payload.new_ticker = trimmedNewTicker;
      }

      await updateInstrument(targetTicker, payload);

      onSuccess?.(`Instrumento ${trimmedNewTicker} actualizado correctamente.`);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al actualizar instrumento: ${msg}`);
    } finally {
      setLoading(false);
    }
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
        onSuccess?.(`Cotización en fecha de análisis obtenida de Yahoo: ${res.analysis_reference_price}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al consultar Yahoo Finance: ${msg}`);
    } finally {
      setFetchingHistorical(false);
    }
  };

  const handleFetchHistoricalForAdd = async () => {
    if (!addTicker.trim() || !addAnalysisDate) {
      onError?.('Introduce primero el ticker y la fecha de análisis.');
      return;
    }
    setFetchingHistorical(true);
    try {
      const res = await fetchAnalysisPrice(addTicker.trim(), addAnalysisDate);
      if (res.status === 'ok') {
        setAddAnalysisPrice(String(res.analysis_reference_price));
        onSuccess?.(`Cotización en fecha de análisis obtenida de Yahoo: ${res.analysis_reference_price}`);
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

  // ── Delete Instrument ────────────────────────────────────────────────── //
  const handleDeleteInstrument = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setLoading(true);
    try {
      await deleteInstrument(targetTicker);
      onSuccess?.(`Instrumento ${targetTicker} eliminado de la base de datos.`);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(`Error al eliminar instrumento: ${msg}`);
    } finally {
      setLoading(false);
      setConfirmDelete(false);
    }
  };

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
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
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
                    Precio Ref. Análisis
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="ej. 190.50"
                    value={addAnalysisPrice}
                    onChange={(e) => setAddAnalysisPrice(e.target.value)}
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
                        className={`flex items-start gap-2 p-2.5 rounded-lg text-xs ${
                          yahooCheckResult.available
                            ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                            : 'bg-rose-500/10 border border-rose-500/20 text-rose-300'
                        }`}
                      >
                        {yahooCheckResult.available ? (
                          <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                        ) : (
                          <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1">
                          {yahooCheckResult.available ? (
                            <div>
                              <p className="font-medium text-emerald-200">
                                Ticker válido y disponible en Yahoo Finance
                              </p>
                              <p className="text-[11px] text-emerald-400/80 mt-0.5 font-mono">
                                Símbolo: {yahooCheckResult.provider_symbol}
                                {yahooCheckResult.price !== undefined && yahooCheckResult.price !== null
                                  ? ` | Precio: ${yahooCheckResult.price} ${yahooCheckResult.currency || ''}`
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
                          onChange={(e) => setEditAnalysisPrice(e.target.value)}
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

                    <div className="pt-2 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800">
                      {/* Yahoo quick fetch */}
                      <button
                        type="button"
                        onClick={handleSingleYahooRefresh}
                        disabled={loading}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                        Consultar Yahoo Finance ahora
                      </button>

                      <div className="flex items-center gap-2">
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
                          className="inline-flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors disabled:opacity-50"
                        >
                          {loading ? (
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
