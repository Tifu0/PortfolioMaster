import type { TranslationKey } from './translations';
import type { InstrumentUpdateRequest } from './types';

export const DEFAULT_EXCHANGE = 'AUTO';
export const DEFAULT_CURRENCY = 'AUTO';

export const POPULAR_EXCHANGES: { labelKey: TranslationKey; value: string }[] = [
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

export const POPULAR_CURRENCIES: { labelKey: TranslationKey; value: string }[] = [
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

export function normalizeTicker(value: string): string {
  return value.trim().toUpperCase();
}

export function parseOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function getTodayLocalDateString(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function resolveOptionalSelectValue(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === '' || trimmed.toUpperCase() === DEFAULT_EXCHANGE) {
    return null;
  }
  return trimmed;
}

export function validateAddInstrumentInput(input: {
  ticker: string;
  fetchYahoo: boolean;
  manualPrice?: string;
  targetPrice?: string;
}): { valid: boolean; errorKey?: TranslationKey } {
  if (!input.ticker.trim()) {
    return { valid: false, errorKey: 'tickerRequiredError' };
  }
  return { valid: true };
}

export function validateEditInstrumentInput(input: {
  ticker: string;
  targetPrice?: string;
  analysisPrice?: string;
  latestPrice?: string;
}): { valid: boolean; errorKey?: TranslationKey } {
  if (!normalizeTicker(input.ticker)) {
    return { valid: false, errorKey: 'tickerEmptyError' };
  }
  return { valid: true };
}

/** Build a canonical PUT /api/instruments/{ticker} payload with optional today-date sync. */
export function buildManualEntryUpdatePayload(
  input: ManualEntryUpdatePayloadInput
): InstrumentUpdateRequest {
  let resolvedAnalysisDate = input.editAnalysisDate ? input.editAnalysisDate.trim() : null;
  let resolvedAnalysisPrice = parseOptionalNumber(input.editAnalysisPrice);

  if (input.updateDateToToday) {
    resolvedAnalysisDate = input.todayDate;
    if (input.isAnalysisPriceManuallyEdited) {
      resolvedAnalysisPrice = parseOptionalNumber(input.editAnalysisPrice);
    } else if (input.latestPrice !== null && Number.isFinite(input.latestPrice)) {
      resolvedAnalysisPrice = input.latestPrice;
    }
  }

  const payload: InstrumentUpdateRequest = {
    company_name: input.editCompany.trim() !== '' ? input.editCompany.trim() : null,
    exchange: resolveOptionalSelectValue(input.editExchange),
    currency: resolveOptionalSelectValue(input.editCurrency),
    target_price: parseOptionalNumber(input.editTargetPrice),
    analysis_reference_price: resolvedAnalysisPrice,
    analysis_date: resolvedAnalysisDate || null,
    start_of_year_price: parseOptionalNumber(input.editSovPrice),
    start_of_year_date: input.editSovDate.trim() !== '' ? input.editSovDate.trim() : null,
    comment: input.editComment.trim() !== '' ? input.editComment.trim() : null,
  };

  const trimmedNewTicker = normalizeTicker(input.editTicker);
  if (trimmedNewTicker && trimmedNewTicker !== normalizeTicker(input.originalTicker)) {
    payload.new_ticker = trimmedNewTicker;
  }
  return payload;
}
