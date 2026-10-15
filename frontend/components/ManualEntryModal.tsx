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
} from 'lucide-react';
import type { Position, Instrument, Exchange } from '@/lib/types';
import {
  createInstrument,
  updateInstrument,
  deleteInstrument,
  refreshInstrument,
  getInstruments,
  getInstrument,
  fetchAnalysisPrice,
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

const POPULAR_CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY', 'CAD', 'AUD', 'SEK', 'NOK'];

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
  const [activeTab, setActiveTab] = useState<'add' | 'edit'>('add');
  const [loading, setLoading] = useState(false);
  const [instrumentsList, setInstrumentsList] = useState<Instrument[]>([]);

  // ── Add Instrument Form State ────────────────────────────────────────── //
  const [addTicker, setAddTicker] = useState('');
  const [addCompanyName, setAddCompanyName] = useState('');
  const [addExchange, setAddExchange] = useState('AUTO');
  const [addCurrency, setAddCurrency] = useState('EUR');
  const [addTargetPrice, setAddTargetPrice] = useState('');
  const [addAnalysisPrice, setAddAnalysisPrice] = useState('');
  const [addAnalysisDate, setAddAnalysisDate] = useState(
    new Date().toISOString().split('T')[0]
  );
  const [addComment, setAddComment] = useState('');
  const [addFetchYahoo, setAddFetchYahoo] = useState(true);
  const [addManualPrice, setAddManualPrice] = useState('');
  const [addManualPrevClose, setAddManualPrevClose] = useState('');

  // ── Edit Instrument Form State ───────────────────────────────────────── //
  const [selectedEditTicker, setSelectedEditTicker] = useState<string>('');
  const [editCompanyName, setEditCompanyName] = useState('');
  const [editTargetPrice, setEditTargetPrice] = useState('');
  const [editAnalysisPrice, setEditAnalysisPrice] = useState('');
  const [editAnalysisDate, setEditAnalysisDate] = useState('');
  const [editComment, setEditComment] = useState('');
  const [editLatestPrice, setEditLatestPrice] = useState('');
  const [editPrevClose, setEditPrevClose] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [fetchingHistorical, setFetchingHistorical] = useState(false);

  // Load available instruments for the edit dropdown
  const loadInstruments = useCallback(async () => {
    try {
      const res = await getInstruments();
      setInstrumentsList(res.instruments || []);
      if (res.instruments && res.instruments.length > 0 && !selectedEditTicker) {
        setSelectedEditTicker(res.instruments[0].user_ticker);
      }
    } catch {
      // Backend might be offline
    }
  }, [selectedEditTicker]);

  useEffect(() => {
    if (isOpen) {
      loadInstruments();
      if (initialTickerToEdit) {
        setActiveTab('edit');
        setSelectedEditTicker(initialTickerToEdit);
      } else {
        setConfirmDelete(false);
      }
    }
  }, [isOpen, initialTickerToEdit, loadInstruments]);

  // When selectedEditTicker changes, fetch details
  useEffect(() => {
    if (!selectedEditTicker) return;
    let isMounted = true;
    (async () => {
      try {
        const detail = await getInstrument(selectedEditTicker);
        if (!isMounted) return;
        const inst = (detail as any).instrument || detail;
        const quote = (detail as any).quote || detail.quote;

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
      } catch (err: unknown) {
        console.error('Error fetching instrument details:', err);
      }
    })();
    return () => {
      isMounted = false;
    };
  }, [selectedEditTicker]);

  if (!isOpen) return null;

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
      setAddTargetPrice('');
      setAddAnalysisPrice('');
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

  // ── Submit Edit Instrument ───────────────────────────────────────────── //
  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedEditTicker) return;

    setLoading(true);
    try {
      await updateInstrument(selectedEditTicker, {
        company_name: editCompanyName.trim() || null,
        target_price: editTargetPrice ? parseFloat(editTargetPrice) : null,
        analysis_reference_price: editAnalysisPrice ? parseFloat(editAnalysisPrice) : null,
        analysis_date: editAnalysisDate || null,
        comment: editComment.trim() || null,
        latest_price: editLatestPrice ? parseFloat(editLatestPrice) : null,
        previous_close: editPrevClose ? parseFloat(editPrevClose) : null,
      });

      onSuccess?.(`Instrumento ${selectedEditTicker} actualizado correctamente.`);
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
    if (!selectedEditTicker) return;
    setFetchingHistorical(true);
    try {
      const res = await fetchAnalysisPrice(selectedEditTicker, editAnalysisDate || undefined);
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
    if (!selectedEditTicker) return;
    setLoading(true);
    try {
      const res = await refreshInstrument(selectedEditTicker);
      if (res.status === 'ok') {
        onSuccess?.(`${selectedEditTicker}: cotización actualizada desde Yahoo Finance.`);
        if (res.price !== undefined && res.price !== null) {
          setEditLatestPrice(String(res.price));
        }
        if (res.previous_close !== undefined && res.previous_close !== null) {
          setEditPrevClose(String(res.previous_close));
        }
      } else {
        onError?.(`${selectedEditTicker}: ${res.detail || 'sin datos disponibles'}`);
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
    if (!selectedEditTicker) return;
    setLoading(true);
    try {
      await deleteInstrument(selectedEditTicker);
      onSuccess?.(`Instrumento ${selectedEditTicker} eliminado de la base de datos.`);
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
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <PlusCircle className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-tight">
                Gestión de Valores Manuales
              </h2>
              <p className="text-xs text-zinc-400">
                Añade o modifica instrumentos y cotizaciones del watchlist
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

        {/* Tab Switcher */}
        <div className="flex border-b border-zinc-800 bg-zinc-950/30 px-6">
          <button
            onClick={() => setActiveTab('add')}
            className={`flex items-center gap-2 py-3 px-4 text-xs font-semibold border-b-2 transition-all ${
              activeTab === 'add'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/[0.04]'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <PlusCircle className="w-3.5 h-3.5" />
            Añadir Nuevo Instrumento
          </button>
          <button
            onClick={() => setActiveTab('edit')}
            className={`flex items-center gap-2 py-3 px-4 text-xs font-semibold border-b-2 transition-all ${
              activeTab === 'edit'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/[0.04]'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Edit3 className="w-3.5 h-3.5" />
            Modificar / Eliminar Existente
          </button>
        </div>

        {/* Modal Body */}
        <div className="overflow-y-auto p-6 space-y-6 flex-1">
          {activeTab === 'add' ? (
            /* ──────────────────────────────────────────────────────────── */
            /* TAB A: ADD NEW INSTRUMENT                                    */
            /* ──────────────────────────────────────────────────────────── */
            <form onSubmit={handleAddSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* User Ticker */}
                <div>
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Ticker <span className="text-rose-400">*</span>
                  </label>
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
                  <label className="block text-xs font-medium text-zinc-300 mb-1">
                    Nombre de la Empresa
                  </label>
                  <input
                    type="text"
                    placeholder="ej. Apple Inc."
                    value={addCompanyName}
                    onChange={(e) => setAddCompanyName(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60"
                  />
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
                      <option key={curr} value={curr} className="bg-zinc-900">
                        {curr}
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
              {instrumentsList.length === 0 ? (
                <div className="p-8 text-center text-zinc-400 text-xs">
                  No hay instrumentos registrados todavía en la base de datos.
                </div>
              ) : (
                <>
                  {/* Select Instrument Dropdown */}
                  <div>
                    <label className="block text-xs font-medium text-zinc-300 mb-1">
                      Selecciona Instrumento para Modificar
                    </label>
                    <select
                      value={selectedEditTicker}
                      onChange={(e) => setSelectedEditTicker(e.target.value)}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                    >
                      {instrumentsList.map((inst) => (
                        <option key={inst.user_ticker} value={inst.user_ticker} className="bg-zinc-900">
                          {inst.user_ticker} — {inst.company_name || inst.user_ticker} ({inst.exchange} / {inst.currency})
                        </option>
                      ))}
                    </select>
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
                          Elimina <strong className="text-zinc-300">{selectedEditTicker}</strong> y todas sus cotizaciones asociadas.
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
