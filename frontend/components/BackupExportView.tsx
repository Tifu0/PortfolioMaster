'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Download,
  Database,
  X,
  ShieldCheck,
} from 'lucide-react';
import {
  exportWatchlist,
  downloadDatabaseBackup,
  getBackupList,
  restoreBackupFile,
  restoreLocalBackup,
} from '@/lib/api';
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { useAuthOptional } from '@/context/AuthContext';
import { useLanguage } from '@/context/LanguageContext';
import { isExpectedUnauthError, shouldFetchBackupsOnTabOpen } from '@/lib/modal-policies';
import type { BackupItem } from '@/lib/types';
import { ExportSection } from './backup/ExportSection';
import { RestoreUploadSection } from './backup/RestoreUploadSection';
import { LocalSnapshotsSection } from './backup/LocalSnapshotsSection';
import { useToast } from './ui/Toast';

export interface BackupExportCallbacks {
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
  onDataRestored?: () => void | Promise<void>;
}

export type BackupExportViewProps = BackupExportCallbacks & (
  | { mode?: 'page'; onClose?: never }
  | { mode: 'modal'; onClose: () => void }
);

export function BackupExportView({
  mode = 'page',
  onClose,
  onSuccess,
  onError,
  onDataRestored,
}: BackupExportViewProps = {}) {
  const portfolioContext = usePortfolioDataOptional();
  const authContext = useAuthOptional();
  const { t } = useLanguage();
  const isAuthConfigured = authContext?.isAuthConfigured ?? false;
  const isAuthenticated = Boolean(authContext?.user);
  const router = useRouter();
  const addToast = useToast();

  const [activeTab, setActiveTab] = useState<'export' | 'backup'>('export');
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);
  const [downloadingDb, setDownloadingDb] = useState(false);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [restoringFile, setRestoringFile] = useState(false);
  const [confirmFileRestore, setConfirmFileRestore] = useState(false);
  const [backupToRestore, setBackupToRestore] = useState<BackupItem | null>(null);
  const [restoringLocal, setRestoringLocal] = useState(false);

  const notify = (type: 'success' | 'error', message: string) => {
    addToast(type, message, mode === 'page' ? null : undefined);
    const callback = type === 'success' ? onSuccess : onError;
    callback?.(message);
  };

  const refreshAfterRestore = async () => {
    await portfolioContext?.refreshPortfolioData({ silent: true });
    await onDataRestored?.();
    if (mode === 'page') router.refresh();
    else onClose?.();
  };

  const fetchBackups = useCallback(async () => {
    setLoadingBackups(true);
    try {
      const res = await getBackupList();
      setBackups(res.backups || []);
    } catch (err: unknown) {
      if (!isExpectedUnauthError(err)) {
        console.warn('Could not load local backups:', err);
      }
    } finally {
      setLoadingBackups(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    if (shouldFetchBackupsOnTabOpen({ activeTab, isAuthConfigured, isAuthenticated })) {
      void Promise.resolve().then(() => {
        if (!ignore) {
          fetchBackups();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [activeTab, isAuthConfigured, isAuthenticated, fetchBackups]);

  const handleExport = async (format: 'csv' | 'excel' | 'json') => {
    setExportingFormat(format);
    try {
      await exportWatchlist(format);
      notify('success', t('exportSuccessToast', { format: format.toUpperCase() }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      notify('error', t('exportErrorToast', { format: format.toUpperCase(), error: msg }));
    } finally {
      setExportingFormat(null);
    }
  };

  const handleDownloadDb = async () => {
    setDownloadingDb(true);
    try {
      await downloadDatabaseBackup();
      notify('success', t('snapshotDownloadedToast'));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      notify('error', t('snapshotDownloadErrorToast', { error: msg }));
    } finally {
      setDownloadingDb(false);
    }
  };

  const handleRestoreFile = async () => {
    if (!selectedFile) return;
    setRestoringFile(true);
    try {
      const res = await restoreBackupFile(selectedFile);
      const count = res.restored_instruments ?? res.active_instruments ?? 0;
      notify(
        'success',
        t('restoreSuccessToast', { name: selectedFile.name, count })
      );

      setSelectedFile(null);
      setConfirmFileRestore(false);

      await refreshAfterRestore();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      notify('error', t('restoreFileErrorToast', { error: msg }));
    } finally {
      setRestoringFile(false);
    }
  };

  const handleRestoreLocal = async (filename: string) => {
    setRestoringLocal(true);
    try {
      const res = await restoreLocalBackup(filename);
      const count = res.restored_instruments ?? res.active_instruments ?? 0;
      notify(
        'success',
        t('restoreSuccessToast', { name: filename, count })
      );

      setBackupToRestore(null);

      await refreshAfterRestore();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      notify('error', t('restoreLocalErrorToast', { error: msg }));
    } finally {
      setRestoringLocal(false);
      setBackupToRestore(null);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className={`flex flex-col gap-4 ${mode === 'page' ? 'rounded-2xl border border-zinc-800/80 bg-zinc-900/60 p-6 backdrop-blur sm:flex-row sm:items-center sm:justify-between sm:p-8' : 'border-b border-zinc-800/80 pb-4'}`}>
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-bold text-white tracking-tight">{t('backupCenterTitle')}</h2>
            <p className="text-xs text-zinc-400 mt-1 max-w-xl">
              {t('backupCenterDesc')}
            </p>
          </div>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-xl p-2 text-zinc-400 transition hover:bg-zinc-800/60 hover:text-white"
              aria-label={t('closeModal')}
            >
              <X className="size-5" aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Tab Toggle */}
        <div className="flex bg-zinc-950 p-1 rounded-xl border border-zinc-800 self-start sm:self-auto">
          <button
            type="button"
            aria-pressed={activeTab === 'export'}
            onClick={() => setActiveTab('export')}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition ${
              activeTab === 'export'
                ? 'bg-zinc-800 text-white shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Download className="w-3.5 h-3.5 text-emerald-400" />
            {t('exportDataTab')}
          </button>
          <button
            type="button"
            aria-pressed={activeTab === 'backup'}
            onClick={() => setActiveTab('backup')}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition ${
              activeTab === 'backup'
                ? 'bg-zinc-800 text-white shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Database className="w-3.5 h-3.5 text-purple-400" />
            {t('restoreBackupsTab')}
          </button>
        </div>
      </div>

      {/* Main Tab View */}
      {activeTab === 'export' ? (
        <div className={mode === 'page' ? 'rounded-2xl bg-zinc-900/40 border border-zinc-800/80 p-6 backdrop-blur' : undefined}>
          <ExportSection
            onExport={handleExport}
            onDownloadDb={handleDownloadDb}
            exportingFormat={exportingFormat}
            downloadingDb={downloadingDb}
          />
        </div>
      ) : (
        <div className={`grid grid-cols-1 gap-6 ${mode === 'page' ? 'lg:grid-cols-2' : ''}`}>
          <RestoreUploadSection
            selectedFile={selectedFile}
            onSelectFile={setSelectedFile}
            confirmFileRestore={confirmFileRestore}
            onSetConfirmFileRestore={setConfirmFileRestore}
            restoringFile={restoringFile}
            onExecuteRestore={handleRestoreFile}
          />
          <LocalSnapshotsSection
            backups={backups}
            loadingBackups={loadingBackups}
            onRefreshBackups={fetchBackups}
            backupToRestore={backupToRestore}
            onSelectBackupToRestore={setBackupToRestore}
            restoringLocal={restoringLocal}
            onExecuteRestoreLocal={handleRestoreLocal}
          />
        </div>
      )}
    </div>
  );
}
