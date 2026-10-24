'use client';

import React, { useCallback, useEffect, useState } from 'react';
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
import { usePortfolioOptional } from '@/context/PortfolioContext';
import type { BackupItem } from '@/lib/types';
import { ExportSection } from './backup/ExportSection';
import { RestoreUploadSection } from './backup/RestoreUploadSection';
import { LocalSnapshotsSection } from './backup/LocalSnapshotsSection';

interface BackupExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
  onDataRestored: () => void;
}

export function BackupExportModal({
  isOpen,
  onClose,
  onSuccess,
  onError,
  onDataRestored,
}: BackupExportModalProps) {
  const portfolioContext = usePortfolioOptional();

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
    if (isOpen && activeTab === 'backup') {
      void Promise.resolve().then(() => {
        if (!ignore) {
          fetchBackups();
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [isOpen, activeTab, fetchBackups]);

  const handleClose = () => {
    setSelectedFile(null);
    setConfirmFileRestore(false);
    setBackupToRestore(null);
    onClose();
  };

  const handleExport = async (format: 'csv' | 'excel' | 'json') => {
    setExportingFormat(format);
    try {
      await exportWatchlist(format);
      onSuccess(`Watchlist exported to ${format.toUpperCase()} successfully.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Failed to export ${format.toUpperCase()}: ${msg}`);
    } finally {
      setExportingFormat(null);
    }
  };

  const handleDownloadDb = async () => {
    setDownloadingDb(true);
    try {
      await downloadDatabaseBackup();
      onSuccess('SQLite database snapshot (.db) downloaded successfully.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Failed to download database snapshot: ${msg}`);
    } finally {
      setDownloadingDb(false);
    }
  };

  const handleRestoreFile = async () => {
    if (!selectedFile) return;
    setRestoringFile(true);
    try {
      const res = await restoreBackupFile(selectedFile);
      onSuccess(
        `Database restored successfully from ${selectedFile.name} (${res.restored_instruments ?? res.active_instruments ?? 0} instruments).`
      );
      if (portfolioContext) {
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      onDataRestored();
      handleClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Failed to restore backup file: ${msg}`);
    } finally {
      setRestoringFile(false);
    }
  };

  const handleRestoreLocal = async (filename: string) => {
    setRestoringLocal(true);
    try {
      const res = await restoreLocalBackup(filename);
      onSuccess(
        `Database restored successfully from ${filename} (${res.restored_instruments ?? res.active_instruments ?? 0} instruments).`
      );
      if (portfolioContext) {
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      onDataRestored();
      handleClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Failed to restore local backup: ${msg}`);
    } finally {
      setRestoringLocal(false);
      setBackupToRestore(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl rounded-2xl bg-zinc-950 border border-zinc-800 shadow-2xl overflow-hidden flex flex-col max-h-[90vh] animate-in zoom-in-95 duration-200"
        role="dialog"
        aria-modal="true"
      >
        {/* Modal Header */}
        <div className="p-5 border-b border-zinc-800/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-tight">
                Backup & Export Center
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5">
                Manage your watchlist snapshots, spreadsheet exports, and atomic restores
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-zinc-400 hover:text-white rounded-xl hover:bg-zinc-800/60 transition"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-zinc-800/80 px-6 pt-3 gap-6 bg-zinc-950">
          <button
            onClick={() => setActiveTab('export')}
            className={`pb-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition ${
              activeTab === 'export'
                ? 'border-emerald-500 text-emerald-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Download className="w-3.5 h-3.5" />
            Export Data
          </button>
          <button
            onClick={() => setActiveTab('backup')}
            className={`pb-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition ${
              activeTab === 'backup'
                ? 'border-emerald-500 text-emerald-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Database className="w-3.5 h-3.5" />
            Restore & Backups
          </button>
        </div>

        {/* Modal Content */}
        <div className="p-6 overflow-y-auto flex flex-col gap-6">
          {activeTab === 'export' ? (
            <ExportSection
              onExport={handleExport}
              onDownloadDb={handleDownloadDb}
              exportingFormat={exportingFormat}
              downloadingDb={downloadingDb}
            />
          ) : (
            <div className="flex flex-col gap-6">
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
      </div>
    </div>
  );
}
