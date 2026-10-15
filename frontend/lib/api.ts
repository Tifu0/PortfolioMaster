/**
 * Typed API client for PortfolioMaster FastAPI backend.
 * Provides functions for every endpoint defined in backend/api/main.py.
 */

import type {
  GenericStatusResponse,
  ImportConfirmResponse,
  ImportPreviewResponse,
  InstrumentCreateRequest,
  InstrumentDetailResponse,
  InstrumentsResponse,
  InstrumentUpdateRequest,
  PositionsResponse,
  PortfolioMetrics,
  RefreshBatchResponse,
  RefreshSingleResponse,
} from './types';

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `API error: ${res.statusText} (${res.status})`;
    let errorData: unknown = null;
    try {
      errorData = await res.json();
      if (typeof errorData === 'object' && errorData !== null && 'detail' in errorData) {
        errorDetail = String((errorData as { detail: unknown }).detail);
      }
    } catch {
      // Body is not JSON
    }
    throw new ApiError(errorDetail, res.status, errorData);
  }
  return res.json() as Promise<T>;
}

/**
 * 1. GET /api/positions
 * Fetches the full watchlist with quotes and server-computed derived columns.
 */
export async function getPositions(cache: RequestCache = 'no-store'): Promise<PositionsResponse> {
  const res = await fetch(`${API_BASE_URL}/api/positions`, {
    cache,
  });
  return handleResponse<PositionsResponse>(res);
}

/**
 * 2. GET /api/instruments
 * Fetches all active instruments.
 */
export async function getInstruments(cache: RequestCache = 'no-store'): Promise<InstrumentsResponse> {
  const res = await fetch(`${API_BASE_URL}/api/instruments`, {
    cache,
  });
  return handleResponse<InstrumentsResponse>(res);
}

/**
 * 3. GET /api/instruments/{ticker}
 * Fetches a single instrument along with its quote.
 */
export async function getInstrument(ticker: string): Promise<InstrumentDetailResponse> {
  const res = await fetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}`, {
    cache: 'no-store',
  });
  return handleResponse<InstrumentDetailResponse>(res);
}

/**
 * 4. POST /api/instruments
 * Creates a new instrument with optional manual price or Yahoo fetch.
 */
export async function createInstrument(
  data: InstrumentCreateRequest
): Promise<InstrumentDetailResponse> {
  const res = await fetch(`${API_BASE_URL}/api/instruments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse<InstrumentDetailResponse>(res);
}

/**
 * 5. PUT /api/instruments/{ticker}
 * Updates instrument fields and optionally quote prices.
 */
export async function updateInstrument(
  ticker: string,
  data: InstrumentUpdateRequest
): Promise<InstrumentDetailResponse> {
  const res = await fetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse<InstrumentDetailResponse>(res);
}

/**
 * 6. DELETE /api/instruments/{ticker}
 * Deletes an instrument and its quotes.
 */
export async function deleteInstrument(ticker: string): Promise<GenericStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}`, {
    method: 'DELETE',
  });
  return handleResponse<GenericStatusResponse>(res);
}

/**
 * 7. POST /api/instruments/{ticker}/refresh
 * Forces a Yahoo Finance quote refresh for a single instrument.
 */
export async function refreshInstrument(ticker: string): Promise<RefreshSingleResponse> {
  const res = await fetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}/refresh`, {
    method: 'POST',
  });
  return handleResponse<RefreshSingleResponse>(res);
}

/**
 * 8. POST /api/refresh
 * Batch refreshes all active instruments from Yahoo Finance.
 */
export async function refreshAll(): Promise<RefreshBatchResponse> {
  const res = await fetch(`${API_BASE_URL}/api/refresh`, {
    method: 'POST',
  });
  return handleResponse<RefreshBatchResponse>(res);
}

/**
 * 9. POST /api/import/preview
 * Uploads a CSV or Excel file and returns validation preview without persisting.
 */
export async function previewImport(file: File | Blob, filename?: string): Promise<ImportPreviewResponse> {
  const formData = new FormData();
  formData.append('file', file, filename || (file instanceof File ? file.name : 'upload.csv'));

  const res = await fetch(`${API_BASE_URL}/api/import/preview`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<ImportPreviewResponse>(res);
}

/**
 * 10. POST /api/import/confirm
 * Commits a list of validated instruments to SQLite.
 */
export async function confirmImport(
  instruments: Array<Record<string, unknown>>
): Promise<ImportConfirmResponse> {
  const res = await fetch(`${API_BASE_URL}/api/import/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruments }),
  });
  return handleResponse<ImportConfirmResponse>(res);
}

/**
 * 11. DELETE /api/database
 * Wipes all instruments and quotes from SQLite database.
 */
export async function wipeDatabase(): Promise<GenericStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/database`, {
    method: 'DELETE',
  });
  return handleResponse<GenericStatusResponse>(res);
}

/**
 * 12. GET /api/metrics
 * Fetches portfolio summary metrics (positions count, best/worst performer, average daily change).
 */
export async function getMetrics(cache: RequestCache = 'no-store'): Promise<PortfolioMetrics> {
  const res = await fetch(`${API_BASE_URL}/api/metrics`, {
    cache,
  });
  return handleResponse<PortfolioMetrics>(res);
}

/**
 * 13. POST /api/instruments/{ticker}/fetch-analysis-price
 * Fetches historical quote from Yahoo Finance for the instrument's analysis date.
 */
export async function fetchAnalysisPrice(
  ticker: string,
  targetDate?: string
): Promise<{ status: string; ticker: string; analysis_date: string; analysis_reference_price: number }> {
  const url = new URL(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}/fetch-analysis-price`);
  if (targetDate) {
    url.searchParams.set('target_date', targetDate);
  }
  const res = await fetch(url.toString(), {
    method: 'POST',
  });
  return handleResponse<{ status: string; ticker: string; analysis_date: string; analysis_reference_price: number }>(res);
}

/**
 * 14. POST /api/instruments/resolve-missing-analysis-prices
 * Batch resolves missing analysis reference prices from Yahoo Finance for instruments with analysis_date.
 */
export async function resolveMissingAnalysisPrices(): Promise<{
  status: string;
  updated: number;
  failed: number;
  skipped: number;
  total: number;
}> {
  const res = await fetch(`${API_BASE_URL}/api/instruments/resolve-missing-analysis-prices`, {
    method: 'POST',
  });
  return handleResponse<{
    status: string;
    updated: number;
    failed: number;
    skipped: number;
    total: number;
  }>(res);
}


