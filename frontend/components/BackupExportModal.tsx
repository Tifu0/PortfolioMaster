'use client';

import React from 'react';
import { BACKUP_EXPORT_TITLE, BackupExportView, type BackupExportCallbacks } from './BackupExportView';

interface BackupExportModalProps extends BackupExportCallbacks {
  isOpen: boolean;
  onClose: () => void;
}

export function BackupExportModal({ isOpen, onClose, ...callbacks }: BackupExportModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={BACKUP_EXPORT_TITLE}
        className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-zinc-800 bg-zinc-950 p-4 shadow-2xl sm:p-5"
      >
        <BackupExportView {...callbacks} mode="modal" onClose={onClose} />
      </div>
    </div>
  );
}
