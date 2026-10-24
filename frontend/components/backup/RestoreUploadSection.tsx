'use client';

import React, { useRef } from 'react';
import {
  Upload,
  Loader2,
  Trash2,
  RotateCcw,
  ShieldAlert,
} from 'lucide-react';

interface RestoreUploadSectionProps {
  selectedFile: File | null;
  onSelectFile: (file: File | null) => void;
  confirmFileRestore: boolean;
  onSetConfirmFileRestore: (confirm: boolean) => void;
  restoringFile: boolean;
  onExecuteRestore: () => Promise<void>;
}

export function RestoreUploadSection({
  selectedFile,
  onSelectFile,
  confirmFileRestore,
  onSetConfirmFileRestore,
  restoringFile,
  onExecuteRestore,
}: RestoreUploadSectionProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      onSelectFile(e.target.files[0]);
      onSetConfirmFileRestore(false);
    }
  };

  return (
    <div className="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 flex flex-col gap-5">
      <div>
        <h4 className="font-semibold text-zinc-200 text-sm flex items-center gap-2">
          <Upload className="w-4 h-4 text-emerald-400" />
          Restore From File (.db or .json)
        </h4>
        <p className="text-xs text-zinc-400 mt-1">
          Upload an existing SQLite database file or a JSON backup snapshot to restore your portfolio watchlist.
        </p>
      </div>

      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".db,.json"
        className="hidden"
      />

      {!selectedFile ? (
        <div
          onClick={() => fileInputRef.current?.click()}
          className="border-2 border-dashed border-zinc-800 hover:border-zinc-700 bg-zinc-950/40 hover:bg-zinc-950/60 rounded-xl p-8 text-center cursor-pointer transition flex flex-col items-center justify-center gap-3"
        >
          <div className="w-10 h-10 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-400">
            <Upload className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <span className="text-xs font-semibold text-zinc-200 block">
              Click to select a backup file (.db or .json)
            </span>
            <span className="text-[11px] text-zinc-500 mt-0.5 block">
              Supports SQLite database files and JSON export snapshots
            </span>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="p-4 rounded-xl bg-zinc-950/80 border border-zinc-800 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 truncate">
              <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
                <Upload className="w-4 h-4" />
              </div>
              <div className="truncate">
                <span className="text-xs font-semibold text-white block truncate">
                  {selectedFile.name}
                </span>
                <span className="text-[11px] text-zinc-500 font-mono">
                  {(selectedFile.size / 1024).toFixed(1)} KB
                </span>
              </div>
            </div>
            <button
              onClick={() => {
                onSelectFile(null);
                onSetConfirmFileRestore(false);
                if (fileInputRef.current) fileInputRef.current.value = '';
              }}
              className="p-1.5 text-zinc-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition"
              title="Remove file"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          {!confirmFileRestore ? (
            <button
              onClick={() => onSetConfirmFileRestore(true)}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold text-zinc-200 bg-zinc-800 hover:bg-zinc-700 rounded-xl transition border border-zinc-700/60"
            >
              <RotateCcw className="w-3.5 h-3.5 text-amber-400" />
              Restore Watchlist from Selected File
            </button>
          ) : (
            <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 flex flex-col gap-3 animate-in fade-in">
              <div className="flex items-start gap-2.5">
                <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div className="text-xs text-amber-300">
                  <strong className="font-semibold block text-amber-200">Confirmation Required</strong>
                  Restoring will atomically replace current watchlist instruments with the contents of{' '}
                  <strong className="font-mono text-white">{selectedFile.name}</strong>. An automatic safety snapshot will be created first.
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  onClick={() => onSetConfirmFileRestore(false)}
                  disabled={restoringFile}
                  className="px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-white bg-zinc-800 hover:bg-zinc-700 rounded-lg transition"
                >
                  Cancel
                </button>
                <button
                  onClick={onExecuteRestore}
                  disabled={restoringFile}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-amber-950 bg-amber-400 hover:bg-amber-300 disabled:opacity-50 rounded-lg transition shadow-sm"
                >
                  {restoringFile ? (
                    <>
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Restoring...
                    </>
                  ) : (
                    'Confirm & Restore'
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
