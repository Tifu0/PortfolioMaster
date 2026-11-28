'use client';

import React, { useEffect } from 'react';
import { useLanguage } from '@/context/LanguageContext';
import { BackupExportView, type BackupExportCallbacks } from './BackupExportView';

interface BackupExportModalProps extends BackupExportCallbacks {
  isOpen: boolean;
  onClose: () => void;
}

export function BackupExportModal({ isOpen, onClose, ...callbacks }: BackupExportModalProps) {
  const { t } = useLanguage();

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm overscroll-contain"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('backupCenterTitle')}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-2xl border border-zinc-800 bg-zinc-950 p-4 shadow-2xl sm:p-5"
      >
        <BackupExportView {...callbacks} mode="modal" onClose={onClose} />
      </div>
    </div>
  );
}
