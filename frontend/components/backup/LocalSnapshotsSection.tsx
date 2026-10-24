'use client';

import React from 'react';
import {
  History,
  RefreshCw,
  Loader2,
  Database,
  AlertTriangle,
} from 'lucide-react';
import type { BackupItem } from '@/lib/types';

interface LocalSnapshotsSectionProps {
  backups: BackupItem[];
  loadingBackups: boolean;
  onRefreshBackups: () => Promise<void>;
  backupToRestore: BackupItem | null;
  onSelectBackupToRestore: (backup: BackupItem | null) => void;
  restoringLocal: boolean;
  onExecuteRestoreLocal: (filename: string) => Promise<void>;
}

export function LocalSnapshotsSection({
  backups,
  loadingBackups,
  onRefreshBackups,
  backupToRestore,
  onSelectBackupToRestore,
  restoringLocal,
  onExecuteRestoreLocal,
}: LocalSnapshotsSectionProps) {
  return (
    <div className="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-zinc-200 text-sm flex items-center gap-2">
            <History className="w-4 h-4 text-emerald-400" />
            Automatic Local Snapshots ({backups.length})
          </h4>
          <p className="text-xs text-zinc-400 mt-1">
            Safety snapshots automatically generated before imports, restores, or wipes stored in the server directory.
          </p>
        </div>
        <button
          onClick={onRefreshBackups}
          disabled={loadingBackups}
          className="p-2 text-zinc-400 hover:text-white bg-zinc-800/80 hover:bg-zinc-800 rounded-xl transition border border-zinc-700/60"
          title="Refresh snapshots list"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loadingBackups ? 'animate-spin text-emerald-400' : ''}`} />
        </button>
      </div>

      {loadingBackups ? (
        <div className="py-8 flex flex-col items-center justify-center gap-2 text-zinc-500 text-xs">
          <Loader2 className="w-5 h-5 animate-spin text-emerald-400" />
          Loading local snapshots...
        </div>
      ) : backups.length === 0 ? (
        <div className="py-8 text-center text-xs text-zinc-500">
          No automatic snapshots available yet.
        </div>
      ) : (
        <div className="flex flex-col gap-2.5 max-h-72 overflow-y-auto pr-1">
          {backups.map((b) => {
            const isTarget = backupToRestore?.filename === b.filename;
            const sizeKb = (b.size_bytes / 1024).toFixed(1);
            const dateStr = b.created_at ? new Date(b.created_at).toLocaleString() : '—';

            return (
              <div
                key={b.filename}
                className={`p-3.5 rounded-xl border transition flex flex-col gap-2.5 ${
                  isTarget
                    ? 'bg-amber-500/5 border-amber-500/30'
                    : 'bg-zinc-950/60 border-zinc-800/80 hover:border-zinc-700'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5 truncate">
                    <Database className="w-4 h-4 text-purple-400 shrink-0" />
                    <div className="truncate">
                      <span className="text-xs font-mono font-medium text-zinc-200 block truncate">
                        {b.filename}
                      </span>
                      <span className="text-[10px] text-zinc-500 flex items-center gap-2">
                        <span>{dateStr}</span>
                        <span>•</span>
                        <span>{sizeKb} KB</span>
                      </span>
                    </div>
                  </div>

                  {!isTarget && (
                    <button
                      onClick={() => onSelectBackupToRestore(b)}
                      disabled={restoringLocal}
                      className="px-2.5 py-1 text-[11px] font-medium text-zinc-300 hover:text-white bg-zinc-800 hover:bg-zinc-700 rounded-lg transition shrink-0 border border-zinc-700/60"
                    >
                      Restore
                    </button>
                  )}
                </div>

                {isTarget && (
                  <div className="pt-2 border-t border-amber-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-2 animate-in fade-in">
                    <span className="text-[11px] text-amber-300 flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                      Restore this snapshot to database?
                    </span>
                    <div className="flex items-center gap-2 self-end sm:self-auto">
                      <button
                        onClick={() => onSelectBackupToRestore(null)}
                        disabled={restoringLocal}
                        className="px-2.5 py-1 text-[11px] font-medium text-zinc-400 hover:text-white bg-zinc-800 hover:bg-zinc-700 rounded-lg transition"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => onExecuteRestoreLocal(b.filename)}
                        disabled={restoringLocal}
                        className="inline-flex items-center gap-1.5 px-3 py-1 text-[11px] font-semibold text-amber-950 bg-amber-400 hover:bg-amber-300 disabled:opacity-50 rounded-lg transition shadow-sm"
                      >
                        {restoringLocal ? (
                          <>
                            <Loader2 className="w-3 h-3 animate-spin" />
                            Restoring...
                          </>
                        ) : (
                          'Confirm'
                        )}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
