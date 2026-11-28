'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { formatStackedDate, type TranslateFn } from '@/lib/watchlist-formatters';

export interface InlineDateCellProps {
  ticker: string;
  analysisDate: string | null;
  currency: string;
  isEditing: boolean;
  isUpdating: boolean;
  t: TranslateFn;
  onStartEditing: (ticker: string, currentDate: string | null) => void;
  onCancelEditing: () => void;
  onSaveDate: (
    ticker: string,
    newDate: string,
    originalDate: string | null,
    currency: string
  ) => void;
}

interface DateEditorInputProps {
  ticker: string;
  analysisDate: string | null;
  currency: string;
  t: TranslateFn;
  onCancelEditing: () => void;
  onSaveDate: (
    ticker: string,
    newDate: string,
    originalDate: string | null,
    currency: string
  ) => void;
}

function DateEditorInput({
  ticker,
  analysisDate,
  currency,
  t,
  onCancelEditing,
  onSaveDate,
}: DateEditorInputProps) {
  const [draftValue, setDraftValue] = useState<string>(() => analysisDate || '');
  const inputRef = useRef<HTMLInputElement>(null);
  const handledRef = useRef(false);

  useEffect(() => {
    try {
      inputRef.current?.showPicker?.();
    } catch {
      // Safe fallback if browser security restricts showPicker
    }
  }, []);

  return (
    <div
      className="flex items-center justify-center w-full"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        type="date"
        aria-label={t('analysisDateInputAria', { ticker })}
        value={draftValue}
        autoFocus
        onChange={(e) => setDraftValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            handledRef.current = true;
            onSaveDate(ticker, draftValue, analysisDate, currency);
          } else if (e.key === 'Escape') {
            e.preventDefault();
            handledRef.current = true;
            onCancelEditing();
          }
        }}
        onBlur={() => {
          if (handledRef.current) return;
          if (draftValue !== (analysisDate || '')) {
            onSaveDate(ticker, draftValue, analysisDate, currency);
          } else {
            onCancelEditing();
          }
        }}
        className="w-full max-w-[90px] bg-zinc-950 border border-emerald-500/80 rounded px-1 py-0.5 text-[11px] text-zinc-100 font-mono tabular-nums focus:outline-none focus:ring-1 focus:ring-emerald-500 shadow-sm transition-all text-center"
      />
    </div>
  );
}

export const InlineDateCell = React.memo(function InlineDateCell({
  ticker,
  analysisDate,
  currency,
  isEditing,
  isUpdating,
  t,
  onStartEditing,
  onCancelEditing,
  onSaveDate,
}: InlineDateCellProps) {
  if (isEditing) {
    return (
      <DateEditorInput
        key={`${ticker}-${analysisDate ?? ''}`}
        ticker={ticker}
        analysisDate={analysisDate}
        currency={currency}
        t={t}
        onCancelEditing={onCancelEditing}
        onSaveDate={onSaveDate}
      />
    );
  }

  const parsed = formatStackedDate(analysisDate);

  if (parsed) {
    return (
      <button
        type="button"
        onClick={() => onStartEditing(ticker, analysisDate)}
        aria-label={t('editAnalysisDateAria', { date: analysisDate || '', ticker })}
        className="flex flex-col items-center justify-center py-0.5 px-1 rounded-md hover:bg-zinc-800/60 cursor-pointer group/date transition-colors select-none text-center mx-auto"
        title={t('clickToEditAnalysisDate', { date: analysisDate || '' })}
      >
        <div className="flex items-center gap-1">
          <span className="text-xs font-semibold text-zinc-200 group-hover/date:text-emerald-400 font-mono tabular-nums leading-tight transition-colors">
            {parsed.dayMonth}
          </span>
          {isUpdating && (
            <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none text-emerald-400 shrink-0" />
          )}
        </div>
        <span className="text-[10px] text-zinc-500 font-mono tabular-nums leading-none mt-0.5">
          {parsed.year}
        </span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onStartEditing(ticker, analysisDate)}
      aria-label={t('assignAnalysisDateAria', { ticker })}
      className="flex items-center justify-center py-0.5 px-1 rounded-md hover:bg-zinc-800/60 cursor-pointer group/date transition-colors select-none text-center mx-auto"
      title={t('clickToAssignAnalysisDate')}
    >
      {isUpdating ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none text-emerald-400" />
      ) : (
        <span className="text-zinc-500 group-hover/date:text-zinc-300 font-mono text-xs tabular-nums transition-colors">
          —
        </span>
      )}
    </button>
  );
});
