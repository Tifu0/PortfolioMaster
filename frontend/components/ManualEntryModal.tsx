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
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { useAuthOptional } from '@/context/AuthContext';
import { useLanguage } from '@/context/LanguageContext';
import type { TranslationKey } from '@/lib/translations';
import { formatCurrency } from '@/lib/formatters';
import { shouldLoadInstrumentsOnModalOpen } from '@/lib/modal-policies';
import type { InstrumentUpdateRequest } from '@/lib/types';

export interface ManualEntryUpdatePayloadInput {
  originalTicker: string;
  editTicker: string;
  editCompany: string;
  editExchange: string;
  editCurrency: string;
  editAnalysisDate: string;
  editAnalysisPrice: string;
  editSovDate: string;
  editSovPrice: string;
  editTargetPrice: string;
  editComment: string;
  editActive?: boolean;
  latestPrice: number | null;
  todayDate: string;
  updateDateToToday: boolean;
  isAnalysisPriceManuallyEdited: boolean;
}

/** Build a canonical PUT /api/instruments/{ticker} payload with optional today-date sync. */
export function buildManualEntryUpdatePayload(
  input: ManualEntryUpdatePayloadInput
): InstrumentUpdateRequest {
  let resolvedAnalysisDate = input.editAnalysisDate ? input.editAnalysisDate.trim() : null;
  let resolvedAnalysisPrice =
    input.editAnalysisPrice.trim() !== '' ? parseFloat(input.editAnalysisPrice) : null;

  if (input.updateDateToToday) {
    resolvedAnalysisDate = input.todayDate;
    if (input.isAnalysisPriceManuallyEdited) {
      resolvedAnalysisPrice =
        input.editAnalysisPrice.trim() !== '' ? parseFloat(input.editAnalysisPrice) : null;
    } else if (input.latestPrice !== null && !Number.isNaN(input.latestPrice)) {
      resolvedAnalysisPrice = input.latestPrice;
    }
  }

  const payload: InstrumentUpdateRequest = {
    company_name: input.editCompany.trim() !== '' ? input.editCompany.trim() : null,
    exchange: input.editExchange !== 'AUTO' && input.editExchange.trim() !== '' ? input.editExchange : null,
    currency: input.editCurrency !== 'AUTO' && input.editCurrency.trim() !== '' ? input.editCurrency : null,
    target_price: input.editTargetPrice.trim() !== '' ? parseFloat(input.editTargetPrice) : null,
    analysis_reference_price: resolvedAnalysisPrice,
    analysis_date: resolvedAnalysisDate || null,
    start_of_year_price: input.editSovPrice.trim() !== '' ? parseFloat(input.editSovPrice) : null,
    start_of_year_date: input.editSovDate.trim() !== '' ? input.editSovDate.trim() : null,
    comment: input.editComment.trim() !== '' ? input.editComment.trim() : null,
  };

  const trimmedNewTicker = input.editTicker.trim().toUpperCase();
  if (trimmedNewTicker && trimmedNewTicker !== input.originalTicker.toUpperCase()) {
    payload.new_ticker = trimmedNewTicker;
  }
  return payload;
}

const POPULAR_EXCHANGES: { labelKey: TranslationKey; value: string }[] = [
  { labelKey: 'exchangeAutoOpt', value: 'AUTO' },
  { labelKey: 'exchangeUsOpt', value: 'US' },
  { labelKey: 'exchangeSpainOpt', value: 'SPAIN' },
  { labelKey: 'exchangeFranceOpt', value: 'FRANCE' },
  { labelKey: 'exchangeGermanyOpt', value: 'GERMANY' },
  { labelKey: 'exchangeUkOpt', value: 'UK' },
  { labelKey: 'exchangeItalyOpt', value: 'ITALY' },
  { labelKey: 'exchangeNetherlandsOpt', value: 'NETHERLANDS' },
  { labelKey: 'exchangeSwitzerlandOpt', value: 'SWITZERLAND' },
  { labelKey: 'exchangeJapanOpt', value: 'JAPAN' },
  { labelKey: 'exchangeHongKongOpt', value: 'HONG_KONG' },
];

const POPULAR_CURRENCIES: { labelKey: TranslationKey; value: string }[] = [
  { labelKey: 'currencyAutoOpt', value: 'AUTO' },
  { labelKey: 'currencyEurOpt', value: 'EUR' },
  { labelKey: 'currencyUsdOpt', value: 'USD' },
  { labelKey: 'currencyGbpOpt', value: 'GBP' },
  { labelKey: 'currencyChfOpt', value: 'CHF' },
  { labelKey: 'currencyJpyOpt', value: 'JPY' },
  { labelKey: 'currencyCadOpt', value: 'CAD' },
  { labelKey: 'currencyAudOpt', value: 'AUD' },
  { labelKey: 'currencySekOpt', value: 'SEK' },
  { labelKey: 'currencyNokOpt', value: 'NOK' },
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
  const { language, t } = useLanguage();
  const portfolioContext = usePortfolioDataOptional();
  const authContext = useAuthOptional();
  const isAuthConfigured = authContext?.isAuthConfigured ?? false;
  const isAuthenticated = Boolean(authContext?.user);

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
      if (e.key === 'Escape' && !isSubmitting) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isSubmitting, onClose]);

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
  }, [isOpen, initialTickerToEdit, isAuthConfigured, isAuthenticated, loadInstruments]);

  if (!isOpen) return null;

  // ── Auto-Detect Company Name and Currency for Add ────────────────────── //
  const handleAutoDetectForAdd = async () => {
    const ticker = addTicker.trim();
    if (!ticker) {
      onError?.(t('enterTickerFirstError'));
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
          t('yahooDetectedSuccess', { name: res.company_name || ticker, currency: res.currency || '' })
        );
      } else {
        onError?.(res.message || t('yahooNotFoundError'));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('yahooQueryError', { error: msg }));
    } finally {
      setCheckingAddYahoo(false);
    }
  };

  // ── Submit Add Instrument ────────────────────────────────────────────── //
  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addTicker.trim()) {
      onError?.(t('tickerRequiredError'));
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

      onSuccess?.(t('instrumentAddedSuccess', { ticker: addTicker.trim() }));
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
      onError?.(t('addInstrumentError', { error: msg }));
    } finally {
      setLoading(false);
    }
  };

  // ── Yahoo Availability Check for Edit Ticker ────────────────────────── //
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
          t('tickerAvailableToast', { ticker, price: formatCurrency(res.price, res.currency, language) })
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
        onError?.(checkData.message || t('couldNotFetchInfo', { ticker: newTicker }));
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
      onSuccess?.(t('tickerSyncedSuccess', { ticker: newTicker }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('tickerSyncError', { error: msg }));
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
      onError?.(t('tickerEmptyError'));
      return;
    }

    setLoading(true);
    setSavingAction(updateDateToToday ? 'with_date' : 'standard');
    try {
      const parsedLatestPrice =
        editLatestPrice.trim() !== '' && !Number.isNaN(parseFloat(editLatestPrice))
          ? parseFloat(editLatestPrice)
          : null;
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
        previous_close: editPrevClose.trim() !== '' ? parseFloat(editPrevClose) : null,
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
        onSuccess?.(t('histQuoteFetched', { price: formatCurrency(res.analysis_reference_price, editCurrency, language) }));
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
        onSuccess?.(t('ytdQuoteFetched', { price: formatCurrency(res.start_of_year_price, editCurrency, language) }));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('yahooQueryError', { error: msg }));
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

  // ── Delete Instrument (Optimistic UI with Rollback) ─────────────────── //
  const handleDeleteInstrument = async () => {
    const targetTicker = originalTickerToEdit || editTicker.trim();
    if (!targetTicker) return;
    setLoading(true);

    // Instant optimistic deletion from UI
    const rollback = portfolioContext?.optimisticDelete(targetTicker);

    try {
      await deleteInstrument(targetTicker);
      onSuccess?.(t('instrumentDeletedSuccess', { ticker: targetTicker }));
      if (portfolioContext) {
        portfolioContext.refreshPortfolioData({ silent: true });
      }
      onClose();
    } catch (err: unknown) {
      // Rollback to previous positions if delete failed
      rollback?.();
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(t('deleteInstrumentError', { error: msg }));
    } finally {
      setLoading(false);
      setConfirmDelete(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 overscroll-contain"
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-entry-modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm transition-opacity motion-reduce:transition-none"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-2xl bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90dvh]">
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-zinc-800 bg-zinc-950/60">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={`w-8 h-8 shrink-0 rounded-lg border flex items-center justify-center ${
                isEditMode
                  ? 'bg-blue-500/10 border-blue-500/20 text-blue-400'
                  : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              }`}
            >
              {isEditMode ? <Edit3 className="w-4 h-4" /> : <PlusCircle className="w-4 h-4" />}
            </div>
            <div className="min-w-0">
              <h2 id="manual-entry-modal-title" className="text-base font-bold text-white tracking-tight truncate">
                {isEditMode
                  ? t('editInstrumentTitle', { ticker: originalTickerToEdit || editTicker })
                  : t('addInstrumentTitle')}
              </h2>
              <p className="text-xs text-zinc-400">
                {isEditMode ? t('editInstrumentSubtitle') : t('addInstrumentSubtitle')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('closeModal')}
            title={t('closeModal')}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="overflow-y-auto overscroll-contain p-4 sm:p-6 space-y-6 flex-1">
          {!isEditMode ? (
            /* ──────────────────────────────────────────────────────────── */
            /* ADD NEW INSTRUMENT                                          */
            /* ──────────────────────────────────────────────────────────── */
            <form onSubmit={handleAddSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* User Ticker */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor="add-ticker-input" className="block text-xs font-medium text-zinc-300">
                      Ticker <span className="text-rose-400">*</span>
                    </label>
                    <button
                      type="button"
                      onClick={handleAutoDetectForAdd}
                      disabled={checkingAddYahoo || !addTicker.trim()}
                      className="inline-flex items-center gap-1 text-[11px] text-emerald-400 hover:text-emerald-300 disabled:opacity-40 disabled:hover:text-emerald-400 transition font-medium"
                      title={t('checkYahooAutoTooltip')}
                    >
                      {checkingAddYahoo ? (
                        <>
                          <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
                          {t('checking')}
                        </>
                      ) : (
                        <>
                          <Search className="w-3 h-3" />
                          {t('checkOnYahoo')}
                        </>
                      )}
                    </button>
                  </div>
                  <input
                    id="add-ticker-input"
                    type="text"
                    required
                    placeholder={t('tickerPlaceholderAdd')}
                    value={addTicker}
                    onChange={(e) => setAddTicker(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60 font-mono uppercase"
                  />
                  <span className="text-[10px] text-zinc-500 mt-1 block">
                    {t('supportsPrefixes')}
                    <code className="text-zinc-400">BME:</code>,{' '}
                    <code className="text-zinc-400">NASDAQ:</code>
                  </span>
                </div>

                {/* Company Name */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label htmlFor="add-company-name-input" className="block text-xs font-medium text-zinc-300">
                      {t('companyName')}
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
                      title={t('enableAutoTooltip')}
                    >
                      {addCompanyName === 'AUTO' || !addCompanyName
                        ? t('autoModeActive')
                        : t('setToAuto')}
                    </button>
                  </div>
                  <input
                    id="add-company-name-input"
                    type="text"
                    placeholder={t('companyPlaceholder')}
                    value={addCompanyName}
                    onChange={(e) => setAddCompanyName(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60"
                  />
                  <span className="text-[10px] text-zinc-500 mt-1 block">
                    {t('autoDescHint', { code: 'AUTO' })}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Exchange */}
                <div>
                  <label htmlFor="add-exchange-select" className="block text-xs font-medium text-zinc-300 mb-1">
                    {t('marketExchange')}
                  </label>
                  <select
                    id="add-exchange-select"
                    value={addExchange}
                    onChange={(e) => setAddExchange(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60"
                  >
                    {POPULAR_EXCHANGES.map((ex) => (
                      <option key={ex.value} value={ex.value} className="bg-zinc-900">
                        {t(ex.labelKey)}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Currency */}
                <div>
                  <label htmlFor="add-currency-select" className="block text-xs font-medium text-zinc-300 mb-1">
                    {t('currencyLabel')}
                  </label>
                  <select
                    id="add-currency-select"
                    value={addCurrency}
                    onChange={(e) => setAddCurrency(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                  >
                    {POPULAR_CURRENCIES.map((curr) => (
                      <option key={curr.value} value={curr.value} className="bg-zinc-900">
                        {t(curr.labelKey)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Price Targets */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <div>
                  <label htmlFor="add-target-price-input" className="block text-xs font-medium text-zinc-300 mb-1">
                    {t('targetPriceLabel')}
                  </label>
                  <input
                    id="add-target-price-input"
                    type="number"
                    step="0.01"
                    placeholder={t('targetPricePlaceholder')}
                    value={addTargetPrice}
                    onChange={(e) => setAddTargetPrice(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60 font-mono"
                  />
                </div>
                <div>
                  <label htmlFor="add-analysis-date-input" className="block text-xs font-medium text-zinc-300 mb-1">
                    {t('analysisDateLabel')}
                  </label>
                  <input
                    id="add-analysis-date-input"
                    type="date"
                    value={addAnalysisDate}
                    onChange={(e) => setAddAnalysisDate(e.target.value)}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-emerald-500/60 font-mono"
                  />
                  <span className="text-[10px] text-zinc-500 mt-1 block">
                    {t('analysisDateHint')}
                  </span>
                </div>
              </div>

              {/* Comment / Thesis */}
              <div>
                <label htmlFor="add-comment-input" className="block text-xs font-medium text-zinc-300 mb-1">
                  {t('commentThesisLabel')}
                </label>
                <textarea
                  id="add-comment-input"
                  rows={2}
                  placeholder={t('commentThesisPlaceholder')}
                  value={addComment}
                  onChange={(e) => setAddComment(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/60 resize-none"
                />
              </div>

              {/* Quote Source Toggle */}
              <div className="pt-2 border-t border-zinc-800/80">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                  <span className="text-xs font-semibold text-zinc-300">
                    {t('initialQuoteSource')}
                  </span>
                  <label className="inline-flex items-center gap-2 cursor-pointer text-xs text-zinc-400">
                    <input
                      type="checkbox"
                      checked={addFetchYahoo}
                      onChange={(e) => setAddFetchYahoo(e.target.checked)}
                      className="rounded bg-zinc-950 border-zinc-700 text-emerald-500 focus:ring-emerald-500/20"
                    />
                    {t('autoFetchYahooCheckbox')}
                  </label>
                </div>

                {!addFetchYahoo && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3 rounded-xl bg-zinc-950/60 border border-zinc-800">
                    <div>
                      <label htmlFor="add-manual-price-input" className="block text-xs font-medium text-zinc-300 mb-1">
                        {t('manualLastPrice')}
                      </label>
                      <input
                        id="add-manual-price-input"
                        type="number"
                        step="0.01"
                        placeholder={t('example175')}
                        value={addManualPrice}
                        onChange={(e) => setAddManualPrice(e.target.value)}
                        className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-200 font-mono"
                      />
                    </div>
                    <div>
                      <label htmlFor="add-manual-prev-close-input" className="block text-xs font-medium text-zinc-300 mb-1">
                        {t('manualPrevClose')}
                      </label>
                      <input
                        id="add-manual-prev-close-input"
                        type="number"
                        step="0.01"
                        placeholder={t('example174')}
                        value={addManualPrevClose}
                        onChange={(e) => setAddManualPrevClose(e.target.value)}
                        className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm text-zinc-200 font-mono"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Submit Button */}
              <div className="pt-4 flex flex-wrap justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
                >
                  {t('cancel')}
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors disabled:opacity-50 shadow-lg shadow-emerald-950/40"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                      {t('saving')}
                    </>
                  ) : (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      {t('saveInstrument')}
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
                      {originalTickerToEdit && editTicker.trim().toUpperCase() !== originalTickerToEdit.toUpperCase() && (
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

                        {yahooCheckResult.available && editTicker.trim().toUpperCase() !== originalTickerToEdit.toUpperCase() && (
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
                            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" /> : null}
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
          )}
        </div>
      </div>
    </div>
  );
}
