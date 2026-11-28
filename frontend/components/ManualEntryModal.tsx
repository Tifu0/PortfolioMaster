'use client';

// 'use client' is required because this modal shell manages dialog keyboard
// dismissal and coordinates active add/edit form busy state.

import React, { useEffect, useState } from 'react';
import { Edit3, PlusCircle, X } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { AddInstrumentForm } from './instrument-modal/AddInstrumentForm';
import { EditInstrumentForm } from './instrument-modal/EditInstrumentForm';

export {
  buildManualEntryUpdatePayload,
  type ManualEntryUpdatePayloadInput,
} from '@/lib/instrument-constants';

export interface ManualEntryModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTickerToEdit?: string | null;
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
}

export function ManualEntryModal({
  isOpen,
  onClose,
  initialTickerToEdit,
  onSuccess,
  onError,
}: ManualEntryModalProps) {
  const { t } = useLanguage();
  const [isBusy, setIsBusy] = useState(false);

  const isEditMode = Boolean(initialTickerToEdit);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isBusy) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isBusy, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 overscroll-contain"
      role="dialog"
      aria-modal="true"
      aria-labelledby="manual-entry-modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm transition-opacity motion-reduce:transition-none"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-2xl bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90dvh]">
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-zinc-800 bg-zinc-950/60">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={`w-8 h-8 shrink-0 rounded-lg border flex items-center justify-center ${
                isEditMode
                  ? 'bg-blue-500/10 border-blue-500/20 text-blue-400'
                  : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              }`}
            >
              {isEditMode ? <Edit3 className="w-4 h-4" /> : <PlusCircle className="w-4 h-4" />}
            </div>
            <div className="min-w-0">
              <h2 id="manual-entry-modal-title" className="text-base font-bold text-white tracking-tight truncate">
                {isEditMode
                  ? t('editInstrumentTitle', { ticker: initialTickerToEdit ?? '' })
                  : t('addInstrumentTitle')}
              </h2>
              <p className="text-xs text-zinc-400">
                {isEditMode ? t('editInstrumentSubtitle') : t('addInstrumentSubtitle')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('closeModal')}
            title={t('closeModal')}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="overflow-y-auto overscroll-contain p-4 sm:p-6 space-y-6 flex-1">
          {!isEditMode ? (
            <AddInstrumentForm
              onClose={onClose}
              onSuccess={onSuccess}
              onError={onError}
              onBusyChange={setIsBusy}
            />
          ) : (
            <EditInstrumentForm
              key={initialTickerToEdit ?? ''}
              initialTickerToEdit={initialTickerToEdit ?? ''}
              onClose={onClose}
              onSuccess={onSuccess}
              onError={onError}
              onBusyChange={setIsBusy}
            />
          )}
        </div>
      </div>
    </div>
  );
}
