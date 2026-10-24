'use client';

import React, { useCallback, useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import {
  Download,
  Database,
  CheckCircle2,
  AlertTriangle,
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
import { usePortfolioOptional } from '@/context/PortfolioContext';
import type { BackupItem } from '@/lib/types';
import { ExportSection } from './backup/ExportSection';
import { RestoreUploadSection } from './backup/RestoreUploadSection';
import { LocalSnapshotsSection } from './backup/LocalSnapshotsSection';

interface ToastData {
  id: number;
  type: 'success' | 'error';
  message: string;
}

function Toast({
  toast,
  onDismiss,
}: {
  toast: ToastData;
  onDismiss: (id: number) => void;
}) {
  const isSuccess = toast.type === 'success';

  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex items-start gap-3 p-4 rounded-xl border shadow-lg backdrop-blur-md transition-all duration-300 animate-in slide-in-from-top-2 ${
        isSuccess
          ? 'bg-emerald-950/90 border-emerald-500/40 text-emerald-200'
          : 'bg-rose-950/90 border-rose-500/40 text-rose-200'
      }`}
    >
      {isSuccess ? (
        <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
      ) : (
        <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
      )}
      <p className="text-xs font-medium leading-relaxed flex-1">{toast.message}</p>
      <button
        onClick={() => onDismiss(toast.id)}
        className="p-1 rounded-lg hover:bg-white/10 transition text-zinc-400 hover:text-white shrink-0"
        aria-label="Dismiss notification"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export interface BackupExportViewProps {
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
  onDataRestored?: () => void;
}

export function BackupExportView({
  onSuccess: propOnSuccess,
  onError: propOnError,
  onDataRestored: propOnDataRestored,
}: BackupExportViewProps = {}) {
  const portfolioContext = usePortfolioOptional();
  const router = useRouter();

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

  const [toasts, setToasts] = useState<ToastData[]>([]);
  const toastIdRef = useRef(0);

  const addToast = useCallback(
    (type: ToastData['type'], message: string) => {
      const id = ++toastIdRef.current;
      setToasts((prev) => [...prev, { id, type, message }]);
      if (type === 'success' && propOnSuccess) propOnSuccess(message);
      if (type === 'error' && propOnError) propOnError(message);
    },
    [propOnSuccess, propOnError]
  );

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const fetchBackups = useCallback(async () => {
    setLoadingBackups(true);
    try {
      const res = await getBackupList();
      setBackups(res.backups || []);
    } catch (err: unknown) {
      console.warn('Could not load local backups:', err);
    } finally {
      setLoadingBackups(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    if (activeTab === 'backup') {
      void Promise.resolve().then(() => {
        if (!ignore) {
          fetchBackups();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [activeTab, fetchBackups]);

  const handleExport = async (format: 'csv' | 'excel' | 'json') => {
    setExportingFormat(format);
    try {
      await exportWatchlist(format);
      addToast('success', `Watchlist exported to ${format.toUpperCase()} successfully.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Failed to export ${format.toUpperCase()}: ${msg}`);
    } finally {
      setExportingFormat(null);
    }
  };

  const handleDownloadDb = async () => {
    setDownloadingDb(true);
    try {
      await downloadDatabaseBackup();
      addToast('success', 'SQLite database snapshot (.db) downloaded successfully.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Failed to download database snapshot: ${msg}`);
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
      addToast(
        'success',
        `Database restored successfully from ${selectedFile.name} (${count} instruments).`
      );

      setSelectedFile(null);
      setConfirmFileRestore(false);

      if (portfolioContext) {
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      if (propOnDataRestored) {
        propOnDataRestored();
      }
      try {
        router.refresh();
      } catch {
        // Safe fallback in test environments
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Failed to restore backup file: ${msg}`);
    } finally {
      setRestoringFile(false);
    }
  };

  const handleRestoreLocal = async (filename: string) => {
    setRestoringLocal(true);
    try {
      const res = await restoreLocalBackup(filename);
      const count = res.restored_instruments ?? res.active_instruments ?? 0;
      addToast(
        'success',
        `Database restored successfully from ${filename} (${count} instruments).`
      );

      setBackupToRestore(null);

      if (portfolioContext) {
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      if (propOnDataRestored) {
        propOnDataRestored();
      }
      try {
        router.refresh();
      } catch {
        // Safe fallback in test environments
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Failed to restore local backup: ${msg}`);
    } finally {
      setRestoringLocal(false);
      setBackupToRestore(null);
    }
  };

  return (
    <div className="flex flex-col gap-6 relative">
      {/* Toast Notifications */}
      {toasts.length > 0 && (
        <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-md w-full pointer-events-auto">
          {toasts.map((toast) => (
            <Toast key={toast.id} toast={toast} onDismiss={dismissToast} />
          ))}
        </div>
      )}

      {/* Hero / Header Card */}
      <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-6 sm:p-8 backdrop-blur flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight">
              Backup & Export Center
            </h1>
            <p className="text-xs text-zinc-400 mt-1 max-w-xl">
              Export your portfolio data to CSV, Excel, or JSON. Restore database snapshots atomically with automatic safety backups.
            </p>
          </div>
        </div>

        {/* Tab Toggle */}
        <div className="flex bg-zinc-950 p-1 rounded-xl border border-zinc-800 self-start sm:self-auto">
          <button
            onClick={() => setActiveTab('export')}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition ${
              activeTab === 'export'
                ? 'bg-zinc-800 text-white shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Download className="w-3.5 h-3.5 text-emerald-400" />
            Export Data
          </button>
          <button
            onClick={() => setActiveTab('backup')}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-lg transition ${
              activeTab === 'backup'
                ? 'bg-zinc-800 text-white shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Database className="w-3.5 h-3.5 text-purple-400" />
            Restore & Backups
          </button>
        </div>
      </div>

      {/* Main Tab View */}
      {activeTab === 'export' ? (
        <div className="rounded-2xl bg-zinc-900/40 border border-zinc-800/80 p-6 backdrop-blur">
          <ExportSection
            onExport={handleExport}
            onDownloadDb={handleDownloadDb}
            exportingFormat={exportingFormat}
            downloadingDb={downloadingDb}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
