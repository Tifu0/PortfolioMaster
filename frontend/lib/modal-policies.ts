/** Pure UX/network gating policies for modals and backup views. */

import { ApiError } from './api';

export interface ModalInstrumentsLoadInput {
  isEditMode: boolean;
  isAuthConfigured: boolean;
  isAuthenticated: boolean;
  hasInitialTicker: boolean;
}

export interface BackupTabFetchInput {
  activeTab: 'export' | 'backup';
  isAuthConfigured: boolean;
  isAuthenticated: boolean;
}

/** Avoid unauthenticated GET /api/instruments bursts when opening the Add modal or browsing signed out. */
export function shouldLoadInstrumentsOnModalOpen({
  isEditMode,
  isAuthConfigured,
  isAuthenticated,
  hasInitialTicker,
}: ModalInstrumentsLoadInput): boolean {
  if (!isEditMode || hasInitialTicker) return false;
  if (isAuthConfigured && !isAuthenticated) return false;
  return true;
}

/** Avoid unauthenticated GET /api/backup/list calls when Supabase Auth requires a session. */
export function shouldFetchBackupsOnTabOpen({
  activeTab,
  isAuthConfigured,
  isAuthenticated,
}: BackupTabFetchInput): boolean {
  if (activeTab !== 'backup') return false;
  if (isAuthConfigured && !isAuthenticated) return false;
  return true;
}

/** Expected 401 responses trigger the auth flow silently without spamming browser console warnings. */
export function isExpectedUnauthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
