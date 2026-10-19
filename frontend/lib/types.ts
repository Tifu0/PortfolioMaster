/**
 * TypeScript type definitions for PortfolioMaster.
 * Matching Python data models from src/portfoliomaster/core/models.py
 * and FastAPI response shapes from backend/api/main.py.
 */

export type QuoteStatus =
  | 'FRESH'
  | 'DELAYED'
  | 'STALE'
  | 'UNAVAILABLE'
  | 'ERROR';

export type Exchange =
  | 'US'
  | 'SPAIN'
  | 'FRANCE'
  | 'UK'
  | 'GERMANY'
  | 'ITALY'
  | 'NETHERLANDS'
  | 'BELGIUM'
  | 'PORTUGAL'
  | 'SWITZERLAND'
  | 'SWEDEN'
  | 'DENMARK'
  | 'NORWAY'
  | 'FINLAND'
  | 'POLAND'
  | 'AUSTRIA'
  | 'GREECE'
  | 'IRELAND'
  | 'AUSTRALIA'
  | 'SOUTH_KOREA'
  | 'JAPAN'
  | 'HONG_KONG'
  | 'TAIWAN'
  | 'CHINA'
  | 'INDIA'
  | 'CANADA'
  | 'BRAZIL'
  | 'MEXICO'
  | 'ARGENTINA'
  | 'SINGAPORE'
  | 'NEW_ZEALAND'
  | 'TURKEY'
  | 'SAUDI_ARABIA'
  | 'INDONESIA'
  | 'MALAYSIA'
  | 'THAILAND'
  | 'PHILIPPINES'
  | 'UNKNOWN';

export interface Instrument {
  id: number | null;
  user_ticker: string;
  provider_symbol: string | null;
  exchange: Exchange | string;
  currency: string;
  company_name: string;
  analysis_date: string | null; // ISO Date YYYY-MM-DD
  analysis_reference_price: number | null;
  start_of_year_date?: string | null; // ISO Date YYYY-MM-DD
  start_of_year_price?: number | null;
  target_price: number | null;
  comment: string;
  active: boolean;
}

export interface Quote {
  id: number | null;
  instrument_id: number | null;
  price: number | null;
  previous_close: number | null;
  quote_timestamp: string | null; // ISO datetime
  fetched_at: string | null;      // ISO datetime
  provider: string;
  status: QuoteStatus | string;
  error_message: string | null;
}

export interface Position {
  id: number | null;
  user_ticker: string;
  provider_symbol: string | null;
  exchange: string;
  currency: string;
  company_name: string;
  analysis_date: string | null;
  analysis_reference_price: number | null;
  start_of_year_date?: string | null;
  start_of_year_price?: number | null;
  target_price: number | null;
  comment: string;
  active: boolean;

  // Quote data
  latest_price: number | null;
  previous_close: number | null;
  quote_status: QuoteStatus | string | null;
  quote_provider: string | null;
  quote_fetched_at: string | null;

  // Server-computed derived columns
  daily_variation: number | null;
  daily_variation_valid: boolean;
  variation_since_analysis: number | null;
  variation_since_analysis_valid: boolean;
  ytd_variation: number | null;
  ytd_variation_valid: boolean;
  decline_to_target: number | null;
  decline_to_target_valid: boolean;
}

export interface PositionsResponse {
  positions: Position[];
  count: number;
}

export interface InstrumentsResponse {
  instruments: Instrument[];
  count: number;
}

export interface InstrumentDetailResponse {
  id?: number | null;
  user_ticker?: string;
  provider_symbol?: string | null;
  exchange?: string;
  currency?: string;
  company_name?: string;
  analysis_date?: string | null;
  analysis_reference_price?: number | null;
  start_of_year_date?: string | null;
  start_of_year_price?: number | null;
  target_price?: number | null;
  comment?: string;
  active?: boolean;
  instrument?: Instrument;
  quote?: Quote | null;
  [key: string]: unknown;
}

export interface InstrumentCreateRequest {
  user_ticker: string;
  company_name?: string;
  exchange?: string;
  currency?: string;
  target_price?: number | null;
  analysis_reference_price?: number | null;
  analysis_date?: string | null;
  start_of_year_price?: number | null;
  start_of_year_date?: string | null;
  comment?: string;
  fetch_yahoo?: boolean;
  manual_price?: number | null;
  manual_previous_close?: number | null;
}

export interface InstrumentUpdateRequest {
  new_ticker?: string | null;
  company_name?: string | null;
  exchange?: string | null;
  currency?: string | null;
  target_price?: number | null;
  analysis_reference_price?: number | null;
  analysis_date?: string | null;
  start_of_year_price?: number | null;
  start_of_year_date?: string | null;
  comment?: string | null;
  latest_price?: number | null;
  previous_close?: number | null;
}

export interface CheckYahooResponse {
  status?: string;
  available: boolean;
  ticker?: string;
  provider_symbol?: string;
  exchange?: string;
  currency?: string;
  price?: number;
  previous_close?: number;
  message?: string;
  company_name?: string;
}

export interface RefreshBatchResponse {
  status: string;
  updated: number;
  failed: number;
  total: number;
  [key: string]: unknown;
}

export interface RefreshSingleResponse {
  status: string;
  price?: number | null;
  previous_close?: number | null;
  analysis_reference_price?: number | null;
  start_of_year_price?: number | null;
  provider?: string;
  quote_status?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface ImportPreviewResponse {
  instruments: Instrument[];
  errors: string[];
  unresolved: string[];
  warnings: string[];
  valid_count: number;
}

export interface ImportConfirmResponse {
  status: string;
  committed: number;
  errors: string[];
}

export interface GenericStatusResponse {
  status: string;
  detail?: string;
  [key: string]: unknown;
}

export interface PerformerSummary {
  user_ticker: string;
  company_name: string;
  daily_variation: number;
  latest_price: number | null;
  currency: string;
}

export interface PortfolioMetrics {
  total_positions: number;
  positions_with_quotes: number;
  best_performer: PerformerSummary | null;
  worst_performer: PerformerSummary | null;
  average_daily_change: number | null;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
}

export interface AppConfig {
  status: string;
  refresh_interval_seconds: number;
  batch_size: number;
  last_refresh_at?: string | null;
  last_refresh_result?: RefreshBatchResponse | null;
}

export interface BackupItem {
  filename: string;
  size_bytes: number;
  created_at: string;
  type: string;
}

export interface BackupListResponse {
  status: string;
  backups: BackupItem[];
  count: number;
}

export interface RestoreResponse {
  status: string;
  restored_instruments?: number;
  active_instruments?: number;
  sample_tickers?: string[];
  type?: string;
  filename?: string;
  backup_filename?: string;
  detail?: string;
}

