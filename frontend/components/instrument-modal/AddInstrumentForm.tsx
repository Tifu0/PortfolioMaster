'use client';

// 'use client' is required because this form manages local input state,
// Yahoo auto-detection, validation, and instrument creation requests.

import React, { useEffect, useState } from 'react';
import { Check, Loader2, Search } from 'lucide-react';
import { checkYahooTicker, createInstrument } from '@/lib/api';
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { useLanguage } from '@/context/LanguageContext';
import {
  DEFAULT_CURRENCY,
  DEFAULT_EXCHANGE,
  POPULAR_CURRENCIES,
  POPULAR_EXCHANGES,
  getTodayLocalDateString,
  normalizeTicker,
  parseOptionalNumber,
  validateAddInstrumentInput,
} from '@/lib/instrument-constants';

export interface AddInstrumentFormProps {
  onClose: () => void;
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
  onBusyChange?: (busy: boolean) => void;
}

export function AddInstrumentForm({
  onClose,
  onSuccess,
  onError,
  onBusyChange,
}: AddInstrumentFormProps) {
  const { t } = useLanguage();
  const portfolioContext = usePortfolioDataOptional();

  const [loading, setLoading] = useState(false);
  const [checkingAddYahoo, setCheckingAddYahoo] = useState(false);
  const [addTicker, setAddTicker] = useState('');
  const [addCompanyName, setAddCompanyName] = useState('');
  const [addExchange, setAddExchange] = useState(DEFAULT_EXCHANGE);
  const [addCurrency, setAddCurrency] = useState(DEFAULT_CURRENCY);
  const [addTargetPrice, setAddTargetPrice] = useState('');
  const [addAnalysisDate, setAddAnalysisDate] = useState(() => getTodayLocalDateString());
  const [addComment, setAddComment] = useState('');
  const [addFetchYahoo, setAddFetchYahoo] = useState(true);
  const [addManualPrice, setAddManualPrice] = useState('');
  const [addManualPrevClose, setAddManualPrevClose] = useState('');

  const isBusy = loading || checkingAddYahoo;

  useEffect(() => {
    onBusyChange?.(isBusy);
  }, [isBusy, onBusyChange]);

  useEffect(() => {
    return () => {
      onBusyChange?.(false);
    };
  }, [onBusyChange]);

  const handleAutoDetectForAdd = async () => {
    const ticker = normalizeTicker(addTicker);
    if (!ticker) {
      onError?.(t('enterTickerFirstError'));
      return;
    }
    setCheckingAddYahoo(true);
    try {
      const res = await checkYahooTicker(
        ticker,
        addCurrency === DEFAULT_CURRENCY ? undefined : addCurrency
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
          t('yahooDetectedSuccess', {
            name: res.company_name || ticker,
            currency: res.currency || '',
          })
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

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validation = validateAddInstrumentInput({
      ticker: addTicker,
      fetchYahoo: addFetchYahoo,
      manualPrice: addManualPrice,
      targetPrice: addTargetPrice,
    });
    if (!validation.valid) {
      onError?.(t(validation.errorKey ?? 'tickerRequiredError'));
      return;
    }

    const normalizedTicker = normalizeTicker(addTicker);

    setLoading(true);
    try {
      await createInstrument({
        user_ticker: normalizedTicker,
        company_name: addCompanyName.trim() || undefined,
        exchange: addExchange,
        currency: normalizeTicker(addCurrency),
        target_price: parseOptionalNumber(addTargetPrice),
        analysis_reference_price: null,
        analysis_date: addAnalysisDate && addAnalysisDate.trim() ? addAnalysisDate.trim() : null,
        start_of_year_price: null,
        start_of_year_date: null,
        comment: addComment.trim(),
        fetch_yahoo: addFetchYahoo,
        manual_price: !addFetchYahoo ? parseOptionalNumber(addManualPrice) : null,
        manual_previous_close: !addFetchYahoo ? parseOptionalNumber(addManualPrevClose) : null,
      });

      onSuccess?.(t('instrumentAddedSuccess', { ticker: normalizedTicker }));
      if (portfolioContext) {
        portfolioContext.refreshPortfolioData({ silent: true });
      }
      setAddTicker('');
      setAddCompanyName('');
      setAddExchange(DEFAULT_EXCHANGE);
      setAddCurrency(DEFAULT_CURRENCY);
      if (addTargetPrice) setAddTargetPrice('');
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

  return (
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
                setAddCompanyName(addCompanyName === 'AUTO' || !addCompanyName ? '' : 'AUTO')
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
  );
}
