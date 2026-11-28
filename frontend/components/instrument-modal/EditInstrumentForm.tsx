'use client';

// 'use client' is required because this form manages edit/delete state,
// Yahoo ticker checks, historical/YTD lookups, and update mutations.

import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  CalendarCheck,
  Check,
  CheckCircle,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';
import type { CheckYahooResponse, Instrument, InstrumentUpdateRequest } from '@/lib/types';
import {
  checkYahooTicker,
  deleteInstrument,
  fetchAnalysisPrice,
  fetchYtdPrice,
  getInstrument,
  getInstruments,
  refreshInstrument,
  updateInstrument,
} from '@/lib/api';
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { useAuthOptional } from '@/context/AuthContext';
import { useLanguage } from '@/context/LanguageContext';
import { formatCurrency } from '@/lib/formatters';
import { shouldLoadInstrumentsOnModalOpen } from '@/lib/modal-policies';
import {
  DEFAULT_CURRENCY,
  DEFAULT_EXCHANGE,
  buildManualEntryUpdatePayload,
  getTodayLocalDateString,
  normalizeTicker,
  parseOptionalNumber,
  validateEditInstrumentInput,
} from '@/lib/instrument-constants';

export interface EditInstrumentFormProps {
  initialTickerToEdit: string;
  onClose: () => void;
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
  onBusyChange?: (busy: boolean) => void;
}

export function EditInstrumentForm({
  initialTickerToEdit,
  onClose,
  onSuccess,
  onError,
  onBusyChange,
}: EditInstrumentFormProps) {
  const { language, t } = useLanguage();
  const portfolioContext = usePortfolioDataOptional();
  const authContext = useAuthOptional();
  const isAuthConfigured = authContext?.isAuthConfigured ?? false;
  const isAuthenticated = Boolean(authContext?.user);

  const [loading, setLoading] = useState(false);
  const [instrumentsList, setInstrumentsList] = useState<Instrument[]>([]);
  const [originalTickerToEdit, setOriginalTickerToEdit] = useState<string>(initialTickerToEdit);
  const [editTicker, setEditTicker] = useState<string>(initialTickerToEdit);
  const [editCompanyName, setEditCompanyName] = useState('');
  const [editExchange, setEditExchange] = useState(DEFAULT_EXCHANGE);
  const [editCurrency, setEditCurrency] = useState(DEFAULT_CURRENCY);
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

  const isSubmitting = loading || fetchingHistorical || checkingYahoo || syncingTickerData;

  useEffect(() => {
    onBusyChange?.(isSubmitting);
  }, [isSubmitting, onBusyChange]);

  useEffect(() => {
    return () => {
      onBusyChange?.(false);
    };
  }, [onBusyChange]);

  const loadInstruments = useCallback(async () => {
    try {
      const res = await getInstruments();
      setInstrumentsList(res.instruments || []);
    } catch {
      // Backend might be offline
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    void Promise.resolve().then(async () => {
      if (!isMounted) return;
      const targetTicker = initialTickerToEdit;
      if (
        shouldLoadInstrumentsOnModalOpen({
          isEditMode: Boolean(targetTicker),
          isAuthConfigured,
          isAuthenticated,
          hasInitialTicker: Boolean(targetTicker),
        })
      ) {
        loadInstruments();
      }
      setIsAnalysisPriceManuallyEdited(false);
      setSavingAction(null);

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
        setEditExchange(inst.exchange ? String(inst.exchange) : DEFAULT_EXCHANGE);
        setEditCurrency(inst.currency ? String(inst.currency) : DEFAULT_CURRENCY);
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
  }, [initialTickerToEdit, isAuthConfigured, isAuthenticated, loadInstruments]);

  const handleCheckYahoo = async () => {
    const ticker = editTicker.trim();
    if (!ticker) {
      onError?.(t('enterTickerToVerify'));
      return;
    }
    setCheckingYahoo(true);
    setYahooCheckResult(null);
    try {
      const res = await checkYahooTicker(ticker);
      setYahooCheckResult(res);
      if (res.available) {
        onSuccess?.(
          t('tickerAvailableToast', {
            ticker,
            price: formatCurrency(res.price, res.currency, language),
          })
        );
        if (res.price !== undefined && res.price !== null && !editLatestPrice) {
          setEditLatestPrice(String(res.price));
        }
        if (res.company_name && !editCompanyName) {
          setEditCompanyName(res.company_name);
        }
      } else {
        onError?.(res.message || t('tickerUnavailableError', { ticker }));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('yahooQueryError', { error: msg }));
      setYahooCheckResult({
        available: false,
        message: msg,
      });
    } finally {
      setCheckingYahoo(false);
    }
  };

  const handleConfirmTickerChange = async () => {
    const newTicker = normalizeTicker(editTicker);
    if (!newTicker) return;

    setSyncingTickerData(true);
    try {
      let checkData = yahooCheckResult;
      if (!checkData || !checkData.available || checkData.ticker?.toUpperCase() !== newTicker) {
        checkData = await checkYahooTicker(newTicker);
        setYahooCheckResult(checkData);
      }

      if (!checkData.available) {
        onError?.(checkData.message || t('couldNotFetchInfo', { ticker: newTicker }));
        return;
      }

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

      setEditAnalysisPrice('');
      setEditStartOfYearPrice('');

      const targetDate = editAnalysisDate || getTodayLocalDateString();
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
      onSuccess?.(t('tickerSyncedSuccess', { ticker: newTicker }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('tickerSyncError', { error: msg }));
    } finally {
      setSyncingTickerData(false);
    }
  };

  const handleSave = async (updateDateToToday: boolean = false) => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;

    const validation = validateEditInstrumentInput({
      ticker: editTicker,
      targetPrice: editTargetPrice,
      analysisPrice: editAnalysisPrice,
      latestPrice: editLatestPrice,
    });
    if (!validation.valid) {
      onError?.(t(validation.errorKey ?? 'tickerEmptyError'));
      return;
    }

    const trimmedNewTicker = normalizeTicker(editTicker);

    setLoading(true);
    setSavingAction(updateDateToToday ? 'with_date' : 'standard');
    try {
      const parsedLatestPrice = parseOptionalNumber(editLatestPrice);
      const payload: InstrumentUpdateRequest = {
        ...buildManualEntryUpdatePayload({
          originalTicker: targetTicker,
          editTicker,
          editCompany: editCompanyName,
          editExchange,
          editCurrency,
          editAnalysisDate,
          editAnalysisPrice,
          editSovDate: editStartOfYearDate,
          editSovPrice: editStartOfYearPrice,
          editTargetPrice,
          editComment,
          latestPrice: parsedLatestPrice,
          todayDate: getTodayLocalDateString(),
          updateDateToToday,
          isAnalysisPriceManuallyEdited,
        }),
        latest_price: parsedLatestPrice,
        previous_close: parseOptionalNumber(editPrevClose),
      };
      const resolvedAnalysisDate = payload.analysis_date ?? null;
      const resolvedAnalysisPrice = payload.analysis_reference_price ?? null;

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
          ? t('instrumentUpdatedToday', { ticker: trimmedNewTicker })
          : t('instrumentUpdated', { ticker: trimmedNewTicker })
      );
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('updateInstrumentError', { error: msg }));
    } finally {
      setLoading(false);
      setSavingAction(null);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await handleSave(false);
  };

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
        onSuccess?.(
          t('histQuoteFetched', {
            price: formatCurrency(res.analysis_reference_price, editCurrency, language),
          })
        );
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('yahooQueryError', { error: msg }));
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
        onSuccess?.(
          t('ytdQuoteFetched', {
            price: formatCurrency(res.start_of_year_price, editCurrency, language),
          })
        );
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('yahooQueryError', { error: msg }));
    } finally {
      setFetchingHistorical(false);
    }
  };

  const handleSingleYahooRefresh = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setLoading(true);
    try {
      const res = await refreshInstrument(targetTicker);
      if (res.status === 'ok') {
        onSuccess?.(t('quoteUpdatedYahoo', { ticker: targetTicker }));
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
        onError?.(`${targetTicker}: ${res.detail || t('noDataAvailableShort')}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('yahooQueryError', { error: msg }));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteInstrument = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setLoading(true);

    const rollback = portfolioContext?.optimisticDelete(targetTicker);

    try {
      await deleteInstrument(targetTicker);
      onSuccess?.(t('instrumentDeletedSuccess', { ticker: targetTicker }));
      if (portfolioContext) {
        portfolioContext.refreshPortfolioData({ silent: true });
      }
      onClose();
    } catch (err: unknown) {
      rollback?.();
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('deleteInstrumentError', { error: msg }));
    } finally {
      setLoading(false);
      setConfirmDelete(false);
    }
  };

  return (
    <div className="space-y-5">
      {!originalTickerToEdit && instrumentsList.length === 0 ? (
        <div className="p-8 text-center text-zinc-400 text-xs">
          {t('noInstrumentsInDb')}
        </div>
      ) : (
        <>
          {/* Ticker Input Field & Yahoo Finance Availability Check */}
          <div className="bg-zinc-900/60 p-3.5 rounded-xl border border-zinc-800/80 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label htmlFor="edit-ticker-input" className="block text-xs font-medium text-zinc-300">
                {t('instrumentTickerLabel')}
              </label>
              {originalTickerToEdit &&
                normalizeTicker(editTicker) !== normalizeTicker(originalTickerToEdit) && (
                  <span className="text-[10px] text-amber-400 font-medium">
                    {t('changingOriginalTicker', { ticker: originalTickerToEdit })}
                  </span>
                )}
            </div>
            <div className="flex flex-wrap sm:flex-nowrap gap-2">
              <div className="relative flex-1 min-w-[160px]">
                <input
                  id="edit-ticker-input"
                  type="text"
                  value={editTicker}
                  onChange={(e) => {
                    setEditTicker(e.target.value.toUpperCase());
                    setYahooCheckResult(null);
                  }}
                  placeholder="AAPL, MC.PA, SAN.MC..."
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-100 font-mono font-semibold tracking-wide focus:outline-none focus:border-emerald-500/60 uppercase"
                />
              </div>
              <button
                type="button"
                onClick={handleCheckYahoo}
                disabled={checkingYahoo || !editTicker.trim()}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-50 transition-colors whitespace-nowrap"
                title={t('checkTickerAvailabilityTitle')}
              >
                {checkingYahoo ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                    {t('checking')}
                  </>
                ) : (
                  <>
                    <Search className="w-3.5 h-3.5" />
                    {t('checkOnYahoo')}
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
                          {t('validTickerYahoo')}
                        </p>
                        <p className="text-[11px] text-emerald-400/80 mt-0.5 font-mono">
                          {t('symbolLabel')}
                          {yahooCheckResult.provider_symbol}
                          {yahooCheckResult.company_name ? ` · ${yahooCheckResult.company_name}` : ''}
                          {yahooCheckResult.price !== undefined && yahooCheckResult.price !== null
                            ? ` · ${formatCurrency(yahooCheckResult.price, yahooCheckResult.currency, language)}`
                            : ''}
                        </p>
                      </div>
                    ) : (
                      <div>
                        <p className="font-medium text-rose-200">
                          {t('notFoundYahoo')}
                        </p>
                        <p className="text-[11px] text-rose-400/80 mt-0.5">
                          {yahooCheckResult.message || t('verifySuffixHint')}
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {yahooCheckResult.available &&
                  normalizeTicker(editTicker) !== normalizeTicker(originalTickerToEdit) && (
                    <button
                      type="button"
                      onClick={handleConfirmTickerChange}
                      disabled={syncingTickerData || loading}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-sm disabled:opacity-50 whitespace-nowrap self-end sm:self-auto cursor-pointer"
                      title={t('confirmChangeTooltip')}
                    >
                      {syncingTickerData ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                          {t('updating')}
                        </>
                      ) : (
                        <>
                          <RefreshCw className="w-3.5 h-3.5" />
                          {t('confirmChangeUpdateData')}
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
                <label htmlFor="edit-company-name-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('companyName')}
                </label>
                <input
                  id="edit-company-name-input"
                  type="text"
                  value={editCompanyName}
                  onChange={(e) => setEditCompanyName(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60"
                />
              </div>
              <div>
                <label htmlFor="edit-target-price-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('targetPriceLabel')}
                </label>
                <input
                  id="edit-target-price-input"
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
                  <label htmlFor="edit-analysis-price-input" className="block text-xs font-medium text-zinc-300">
                    {t('analysisRefPriceLabel')}
                  </label>
                  <button
                    type="button"
                    onClick={handleFetchHistoricalForEdit}
                    disabled={fetchingHistorical || loading}
                    className="text-[10px] text-emerald-400 hover:text-emerald-300 underline font-mono"
                    title={t('fetchQuoteDateTitle')}
                  >
                    {fetchingHistorical ? t('searching') : t('fetchFromYahoo')}
                  </button>
                </div>
                <input
                  id="edit-analysis-price-input"
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
                <label htmlFor="edit-analysis-date-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('analysisDateLabel')}
                </label>
                <input
                  id="edit-analysis-date-input"
                  type="date"
                  value={editAnalysisDate}
                  onChange={(e) => setEditAnalysisDate(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                />
              </div>
              <div>
                <label htmlFor="edit-latest-price-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('lastPriceInputLabel')}
                </label>
                <input
                  id="edit-latest-price-input"
                  type="number"
                  step="0.01"
                  value={editLatestPrice}
                  onChange={(e) => setEditLatestPrice(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                />
              </div>
              <div>
                <label htmlFor="edit-prev-close-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('previousCloseInputLabel')}
                </label>
                <input
                  id="edit-prev-close-input"
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
                  <label htmlFor="edit-ytd-price-input" className="block text-xs font-medium text-zinc-300">
                    {t('ytdRefPriceLabel')}
                  </label>
                  <button
                    type="button"
                    onClick={handleFetchYtdForEdit}
                    disabled={fetchingHistorical || loading}
                    className="text-[10px] text-emerald-400 hover:text-emerald-300 underline font-mono"
                    title={t('fetchYtdTitle')}
                  >
                    {fetchingHistorical ? t('searching') : t('fetchFromYahoo')}
                  </button>
                </div>
                <input
                  id="edit-ytd-price-input"
                  type="number"
                  step="0.01"
                  value={editStartOfYearPrice}
                  onChange={(e) => setEditStartOfYearPrice(e.target.value)}
                  placeholder={t('example150')}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                />
              </div>
              <div>
                <label htmlFor="edit-ytd-date-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('ytdDateLabel')}
                </label>
                <input
                  id="edit-ytd-date-input"
                  type="date"
                  value={editStartOfYearDate}
                  onChange={(e) => setEditStartOfYearDate(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                />
              </div>
            </div>

            <div>
              <label htmlFor="edit-comment-input" className="block text-xs font-medium text-zinc-300 mb-1">
                {t('commentLabel')}
              </label>
              <textarea
                id="edit-comment-input"
                rows={2}
                value={editComment}
                onChange={(e) => setEditComment(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 resize-none"
              />
            </div>

            <div className="pt-3 border-t border-zinc-800 flex flex-wrap items-center justify-between gap-2">
              {/* Yahoo quick fetch */}
              <button
                type="button"
                onClick={handleSingleYahooRefresh}
                disabled={isSubmitting}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shrink-0 whitespace-nowrap"
                title={t('fetchYahooNowTitle')}
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">
                  {t('fetchPrefix')}
                </span>
                Yahoo
              </button>

              <div className="flex flex-wrap items-center justify-end gap-2 ml-auto">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isSubmitting}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors disabled:opacity-50 cursor-pointer whitespace-nowrap"
                >
                  {t('cancel')}
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/20 hover:border-emerald-500/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer whitespace-nowrap"
                  title={t('saveChangesTitle')}
                >
                  {savingAction === 'standard' ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                      {t('saving')}
                    </>
                  ) : (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      {t('saveChanges')}
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => handleSave(true)}
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 shadow-sm shadow-emerald-950/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer whitespace-nowrap"
                  title={t('saveAndUpdateDateTitle')}
                >
                  {savingAction === 'with_date' ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                      {t('updating')}
                    </>
                  ) : (
                    <>
                      <CalendarCheck className="w-3.5 h-3.5" />
                      {t('saveAndUpdateDate')}
                    </>
                  )}
                </button>
              </div>
            </div>
          </form>

          {/* Danger Zone: Delete Instrument */}
          <div className="mt-6 pt-4 border-t border-rose-500/20 bg-rose-500/[0.02] p-4 rounded-xl border">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4 className="text-xs font-semibold text-rose-400 flex items-center gap-1.5">
                  <Trash2 className="w-3.5 h-3.5" />
                  {t('deleteInstrumentTitle')}
                </h4>
                <p className="text-[11px] text-zinc-500 mt-0.5">
                  {t('deleteInstrumentDesc', { ticker: originalTickerToEdit || editTicker })}
                </p>
              </div>

              {confirmDelete ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    className="px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200"
                  >
                    {t('cancel')}
                  </button>
                  <button
                    type="button"
                    onClick={handleDeleteInstrument}
                    disabled={loading}
                    className="px-3 py-1.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 rounded-lg transition-colors flex items-center gap-1.5"
                  >
                    {loading ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                    ) : null}
                    {t('confirmDeletion')}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="px-3 py-1.5 text-xs font-medium text-rose-400 border border-rose-500/30 rounded-lg hover:bg-rose-500/10 transition-colors"
                >
                  {t('delete')}
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
