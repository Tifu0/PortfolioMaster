/**
 * Typed API client for PortfolioMaster FastAPI backend.
 * Provides functions for every endpoint defined in backend/api/main.py.
 */

import type {
  CheckYahooResponse,
  GenericStatusResponse,
  ImportConfirmResponse,
  ImportInstrumentPayload,
  ImportPreviewResponse,
  InstrumentCreateRequest,
  InstrumentDetailResponse,
  InstrumentsResponse,
  InstrumentUpdateRequest,
  PositionsResponse,
  PortfolioMetrics,
  RefreshBatchResponse,
  RefreshProgressEvent,
  RefreshSingleResponse,
  AppConfig,
  BackupListResponse,
  RestoreResponse,
} from './types';
import { getAuthToken } from './supabase';

const isServer = typeof window === 'undefined';

/**
 * Base URL resolution:
 * On client (browser), calls use relative path ('/api/...') hitting Next.js proxy/BFF.
 * On server (SSR), calls use API_BASE_URL or NEXT_PUBLIC_API_URL.
 * Localhost fallback is restricted strictly to non-production development.
 */
const rawApiUrl = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || process.env.BACKEND_URL;
export const API_BASE_URL = isServer
  ? (rawApiUrl ? rawApiUrl.replace(/\/$/, '') : (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:8000'))
  : '';

/**
 * Authenticated fetch wrapper that injects Supabase Bearer JWT token on all outgoing API calls.
 * Dispatches 'portfoliomaster:auth-required' event on 401 Unauthorized to trigger the auth flow.
 */
export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (!headers.has('Authorization')) {
    const token = await getAuthToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  }
  const response = await fetch(input, {
    ...init,
    headers,
  });

  if (response.status === 401 && typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('portfoliomaster:auth-required', {
        detail: { message: 'Tu sesión ha expirado o requiere autenticación. Por favor, identifícate.' },
      })
    );
  }

  return response;
}

function getFullUrl(path: string): URL {
  if (isServer) {
    const rawBackend = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || process.env.BACKEND_URL;
    if (!rawBackend && process.env.NODE_ENV === 'production') {
      throw new Error(
        '[Configuration Error] API_BASE_URL or NEXT_PUBLIC_API_URL is required in production environment for server-side requests.'
      );
    }
    const base = rawBackend ? rawBackend.replace(/\/$/, '') : 'http://localhost:8000';
    return new URL(path.startsWith('/') ? path : `/${path}`, base);
  }
  return new URL(path.startsWith('/') ? path : `/${path}`, window.location.origin);
}

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
  const res = await authFetch(`${API_BASE_URL}/api/positions`, {
    cache,
  });
  return handleResponse<PositionsResponse>(res);
}

/**
 * 2. GET /api/instruments
 * Fetches all active instruments.
 */
export async function getInstruments(cache: RequestCache = 'no-store'): Promise<InstrumentsResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/instruments`, {
    cache,
  });
  return handleResponse<InstrumentsResponse>(res);
}

/**
 * 3. GET /api/instruments/{ticker}
 * Fetches a single instrument along with its quote.
 */
export async function getInstrument(ticker: string): Promise<InstrumentDetailResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}`, {
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
  const res = await authFetch(`${API_BASE_URL}/api/instruments`, {
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
  const res = await authFetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}`, {
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
  const res = await authFetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}`, {
    method: 'DELETE',
  });
  return handleResponse<GenericStatusResponse>(res);
}

/**
 * 7. POST /api/instruments/{ticker}/refresh
 * Forces a Yahoo Finance quote refresh for a single instrument.
 */
export async function refreshInstrument(ticker: string): Promise<RefreshSingleResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/instruments/${encodeURIComponent(ticker)}/refresh`, {
    method: 'POST',
  });
  return handleResponse<RefreshSingleResponse>(res);
}

/**
 * 8. POST /api/refresh
 * Batch refreshes all active instruments from Yahoo Finance.
 */
export async function refreshAll(): Promise<RefreshBatchResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/refresh`, {
    method: 'POST',
  });
  return handleResponse<RefreshBatchResponse>(res);
}

/**
 * 8b. GET /api/refresh/stream
 * Streams batch-by-batch progress via Server-Sent Events (SSE) and returns final summary.
 */
export async function streamRefresh(
  onProgress?: (event: RefreshProgressEvent) => void
): Promise<RefreshBatchResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/refresh/stream?trigger=1`);
  if (!res.ok) {
    throw new ApiError(`Stream refresh failed: ${res.statusText}`, res.status);
  }

  if (!res.body) {
    return refreshAll();
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: RefreshBatchResponse = {
    status: 'ok',
    updated: 0,
    failed: 0,
    total: 0,
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        for (const line of block.split('\n')) {
          if (line.startsWith('data: ')) {
            try {
              const event: RefreshProgressEvent = JSON.parse(line.slice(6));
              if (onProgress) {
                onProgress(event);
              }
              if (event.type === 'complete') {
                finalResult = {
                  status: event.status || 'ok',
                  updated: event.updated ?? 0,
                  failed: event.failed ?? 0,
                  total: event.total ?? event.total_symbols ?? 0,
                  refreshed_count: event.refreshed_count,
                  message: event.message,
                  analysis_prices_updated: event.analysis_prices_updated,
                  ytd_prices_updated: event.ytd_prices_updated,
                };
              }
            } catch {
              // Ignore non-json or comments
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  return finalResult;
}

/**
 * 9. POST /api/import/preview
 * Uploads a CSV or Excel file and returns validation preview without persisting.
 */
export async function previewImport(file: File | Blob, filename?: string): Promise<ImportPreviewResponse> {
  const formData = new FormData();
  formData.append('file', file, filename || (file instanceof File ? file.name : 'upload.csv'));

  const res = await authFetch(`${API_BASE_URL}/api/import/preview`, {
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
  instruments: ImportInstrumentPayload[]
): Promise<ImportConfirmResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/import/confirm`, {
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
  const res = await authFetch(`${API_BASE_URL}/api/database`, {
    method: 'DELETE',
  });
  return handleResponse<GenericStatusResponse>(res);
}

/**
 * 12. GET /api/metrics
 * Fetches portfolio summary metrics (positions count, best/worst performer, average daily change).
 */
export async function getMetrics(cache: RequestCache = 'no-store'): Promise<PortfolioMetrics> {
  const res = await authFetch(`${API_BASE_URL}/api/metrics`, {
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
  const url = getFullUrl(`/api/instruments/${encodeURIComponent(ticker)}/fetch-analysis-price`);
  if (targetDate) {
    url.searchParams.set('target_date', targetDate);
  }
  const res = await authFetch(url.toString(), {
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
  const res = await authFetch(`${API_BASE_URL}/api/instruments/resolve-missing-analysis-prices`, {
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

/**
 * POST /api/instruments/{ticker}/fetch-ytd-price
 * Fetches start of year quote from Yahoo Finance for instrument for current (or given) year.
 */
export async function fetchYtdPrice(
  ticker: string,
  targetYear?: number
): Promise<{ status: string; ticker: string; start_of_year_date: string; start_of_year_price: number }> {
  const url = getFullUrl(`/api/instruments/${encodeURIComponent(ticker)}/fetch-ytd-price`);
  if (targetYear) {
    url.searchParams.set('target_year', String(targetYear));
  }
  const res = await authFetch(url.toString(), {
    method: 'POST',
  });
  return handleResponse<{ status: string; ticker: string; start_of_year_date: string; start_of_year_price: number }>(res);
}

/**
 * POST /api/instruments/resolve-missing-ytd-prices
 * Batch resolves missing start-of-year prices from Yahoo Finance for instruments for the current year.
 */
export async function resolveMissingYtdPrices(): Promise<{
  status: string;
  updated: number;
  failed: number;
  skipped: number;
  total: number;
}> {
  const res = await authFetch(`${API_BASE_URL}/api/instruments/resolve-missing-ytd-prices`, {
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

/**
 * 15. GET /api/instruments/check-yahoo
 * Validates whether a ticker exists and has quotes available on Yahoo Finance.
 */
export async function checkYahooTicker(ticker: string, currency?: string): Promise<CheckYahooResponse> {
  const url = getFullUrl('/api/instruments/check-yahoo');
  url.searchParams.set('ticker', ticker);
  if (currency) url.searchParams.set('currency', currency);
  const res = await authFetch(url.toString(), {
    cache: 'no-store',
  });
  return handleResponse<CheckYahooResponse>(res);
}

/**
 * 16. GET /api/config
 * Retrieves backend runtime configuration (refresh interval, batch size, last refresh status).
 */
export async function getConfig(): Promise<AppConfig> {
  const res = await fetch(`${API_BASE_URL}/api/config`, {
    cache: 'no-store',
  });
  return handleResponse<AppConfig>(res);
}

/**
 * Helper to trigger a browser file download from a Blob.
 */
function triggerFileDownload(blob: Blob, defaultFilename: string, contentDisposition?: string | null): void {
  let filename = defaultFilename;
  if (contentDisposition) {
    const filenameMatch = contentDisposition.match(/filename=["']?([^"';]+)["']?/i);
    if (filenameMatch && filenameMatch[1]) {
      filename = filenameMatch[1].trim();
    }
  }

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  }, 200);
}

/**
 * 17. GET /api/export/{format}
 * Downloads watchlist data in CSV, Excel (.xlsx), or JSON format.
 */
export async function exportWatchlist(format: 'csv' | 'excel' | 'json'): Promise<void> {
  const res = await authFetch(`${API_BASE_URL}/api/export/${format}`);
  if (!res.ok) {
    let errorDetail = `Export failed (${res.status})`;
    try {
      const err = await res.json();
      if (err && err.detail) errorDetail = String(err.detail);
    } catch {
      // not json
    }
    throw new ApiError(errorDetail, res.status);
  }

  const blob = await res.blob();
  const ext = format === 'excel' ? 'xlsx' : format;
  const today = new Date().toISOString().slice(0, 10);
  const defaultFilename = `portfoliomaster_export_${today}.${ext}`;
  const disposition = res.headers.get('Content-Disposition');

  triggerFileDownload(blob, defaultFilename, disposition);
}

/**
 * 18. GET /api/backup/download
 * Downloads atomic raw SQLite database snapshot (.db).
 */
export async function downloadDatabaseBackup(): Promise<void> {
  const res = await authFetch(`${API_BASE_URL}/api/backup/download`);
  if (!res.ok) {
    let errorDetail = `Backup download failed (${res.status})`;
    try {
      const err = await res.json();
      if (err && err.detail) errorDetail = String(err.detail);
    } catch {
      // not json
    }
    throw new ApiError(errorDetail, res.status);
  }

  const blob = await res.blob();
  const today = new Date().toISOString().slice(0, 10);
  const defaultFilename = `portfoliomaster_backup_${today}.db`;
  const disposition = res.headers.get('Content-Disposition');

  triggerFileDownload(blob, defaultFilename, disposition);
}

/**
 * 19. GET /api/backup/list
 * Lists available local automatic snapshots in backups/.
 */
export async function getBackupList(): Promise<BackupListResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/backup/list`, {
    cache: 'no-store',
  });
  return handleResponse<BackupListResponse>(res);
}

/**
 * 20. POST /api/backup/restore
 * Restores database from an uploaded .db or .json file.
 */
export async function restoreBackupFile(file: File): Promise<RestoreResponse> {
  const formData = new FormData();
  formData.append('file', file, file.name);

  const res = await authFetch(`${API_BASE_URL}/api/backup/restore`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<RestoreResponse>(res);
}

/**
 * 21. POST /api/backup/restore/{filename}
 * Restores database from a local automatic snapshot in backups/.
 */
export async function restoreLocalBackup(filename: string): Promise<RestoreResponse> {
  const res = await authFetch(`${API_BASE_URL}/api/backup/restore/${encodeURIComponent(filename)}`, {
    method: 'POST',
  });
  return handleResponse<RestoreResponse>(res);
}



