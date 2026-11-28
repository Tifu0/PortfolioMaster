'use client';

import React, { useState } from 'react';
import { Check, FileText, Loader2, X } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import type { Position } from '@/lib/types';

export interface InstrumentDescriptionPanelProps {
  position: Position;
  colSpan: number;
  onSave: (position: Position, newComment: string) => Promise<void>;
  onClose: (ticker: string) => void;
}

export const InstrumentDescriptionPanel = React.memo(function InstrumentDescriptionPanel({
  position,
  colSpan,
  onSave,
  onClose,
}: InstrumentDescriptionPanelProps) {
  const { t } = useLanguage();
  const ticker = position.user_ticker;
  const [draft, setDraft] = useState<string>(() => position.comment || '');
  const [isSaving, setIsSaving] = useState(false);
  const hasUnsavedChanges = draft !== (position.comment || '');

  const handleSaveClick = async () => {
    setIsSaving(true);
    try {
      await onSave(position, draft);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <tr className="bg-zinc-900/95 border-b border-zinc-800">
      <td colSpan={colSpan} className="px-4 py-3.5 sm:px-6">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4 space-y-3 shadow-lg animate-in fade-in-50 motion-reduce:animate-none duration-150">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                <FileText className="w-4 h-4" />
              </div>
              <div>
                <span className="text-xs font-semibold text-white">
                  {t('companyNotesTitle')}
                </span>
                <span className="text-xs text-zinc-400 ml-2 font-mono">
                  {position.user_ticker} · {position.company_name}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => onClose(ticker)}
              aria-label={t('closeNotesAria', { ticker })}
              className="text-zinc-500 hover:text-zinc-300 p-1 rounded-lg hover:bg-zinc-800 transition"
              title={t('closeNotesTooltip')}
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <textarea
            value={draft}
            aria-label={t('notesTextareaAria', { ticker })}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t('notesPlaceholder', { company: position.company_name })}
            rows={3}
            className="w-full bg-zinc-900/90 border border-zinc-800 rounded-lg p-3 text-xs sm:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all font-sans leading-relaxed resize-y"
          />

          <div className="flex items-center justify-between text-xs pt-0.5">
            <span className="text-zinc-500 text-[11px] font-mono">
              {draft.length} {t('charactersLabel')}
              {hasUnsavedChanges && (
                <span className="ml-2 text-amber-400">• {t('unsavedChanges')}</span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onClose(ticker)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition"
              >
                {t('close')}
              </button>
              <button
                type="button"
                onClick={handleSaveClick}
                disabled={isSaving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
              >
                {isSaving ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                    {t('saving')}
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    {t('saveDescription')}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
});
