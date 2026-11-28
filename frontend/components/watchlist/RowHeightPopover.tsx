'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Edit3,
  FileText,
  RotateCcw,
  Rows3,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import {
  DEFAULT_ROW_HEIGHT,
  MAX_ROW_HEIGHT,
  MIN_ROW_HEIGHT,
  getRowCellPaddingClass,
} from '@/lib/watchlist-formatters';

export interface RowHeightPopoverProps {
  rowHeight: number;
  onRowHeightChange: (newHeight: number) => void;
}

export function RowHeightPopover({
  rowHeight,
  onRowHeightChange,
}: RowHeightPopoverProps) {
  const { t } = useLanguage();
  const [rowHeightOpen, setRowHeightOpen] = useState(false);
  const rowHeightRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!rowHeightOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (rowHeightRef.current && !rowHeightRef.current.contains(e.target as Node)) {
        setRowHeightOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setRowHeightOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [rowHeightOpen]);

  const cellPaddingClass = useMemo(() => getRowCellPaddingClass(rowHeight), [rowHeight]);

  return (
    <div className="relative" ref={rowHeightRef}>
      <button
        type="button"
        onClick={() => setRowHeightOpen((prev) => !prev)}
        aria-label={t('adjustRowHeightAria')}
        aria-expanded={rowHeightOpen}
        className={`h-9 inline-flex items-center gap-1.5 px-2.5 sm:px-3 rounded-lg text-xs font-medium transition-all shrink-0 border cursor-pointer ${
          rowHeightOpen
            ? 'bg-zinc-800 text-indigo-400 border-zinc-600 ring-1 ring-indigo-500/40 shadow-sm'
            : 'bg-zinc-800/90 text-zinc-200 border border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600 shadow-sm'
        }`}
        title={t('adjustRowHeightTooltip')}
      >
        <Rows3 className="w-3.5 h-3.5 text-indigo-400" />
        <span>
          {t('rowHeightShort')} · {rowHeight}px
        </span>
      </button>

      {rowHeightOpen && (
        <div className="absolute right-0 top-full mt-2 w-[calc(100vw-2rem)] sm:w-96 rounded-2xl bg-zinc-900 border border-zinc-800 shadow-2xl p-4 z-[100] animate-in fade-in zoom-in-95 motion-reduce:animate-none duration-150 space-y-3.5">
          {/* Popover Header */}
          <div className="flex items-center justify-between pb-2.5 border-b border-zinc-800/80">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-md bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center">
                <Rows3 className="w-3.5 h-3.5" />
              </div>
              <div>
                <span className="text-xs font-semibold text-white tracking-tight">
                  {t('rowHeightLabel')}
                </span>
                <span className="text-[10px] text-zinc-400 font-mono ml-2">
                  {rowHeight <= 36
                    ? t('densityCompact')
                    : rowHeight <= 54
                    ? t('densityStandard')
                    : t('densitySpacious')}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onRowHeightChange(DEFAULT_ROW_HEIGHT)}
                aria-label={t('rowHeightResetAria')}
                className="text-[11px] text-zinc-400 hover:text-indigo-400 font-medium flex items-center gap-1 transition-colors cursor-pointer"
                title={t('rowHeightResetTitle')}
              >
                <RotateCcw className="w-3 h-3" />
                <span>48px</span>
              </button>
              <button
                type="button"
                onClick={() => setRowHeightOpen(false)}
                aria-label={t('closeRowHeightAria')}
                className="p-1 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/60 transition-colors cursor-pointer"
                title={t('close')}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Slider & Numeric Input */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <label htmlFor="watchlist-row-height-number" className="text-zinc-400 font-medium">
                {t('verticalDensity')}
              </label>
              <div className="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1 focus-within:border-indigo-500/80 focus-within:ring-1 focus-within:ring-indigo-500">
                <input
                  id="watchlist-row-height-number"
                  type="number"
                  aria-label={t('rowHeightNumberAria')}
                  min={MIN_ROW_HEIGHT}
                  max={MAX_ROW_HEIGHT}
                  value={rowHeight}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    if (!isNaN(val)) {
                      onRowHeightChange(val);
                    }
                  }}
                  className="w-12 bg-transparent text-right font-mono text-xs text-white focus:outline-none"
                />
                <span className="text-zinc-500 font-mono text-[11px]">px</span>
              </div>
            </div>

            <input
              type="range"
              aria-label={t('rowHeightSliderAria')}
              min={MIN_ROW_HEIGHT}
              max={MAX_ROW_HEIGHT}
              step={1}
              value={rowHeight}
              onChange={(e) => onRowHeightChange(parseInt(e.target.value, 10))}
              className="w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-indigo-500 hover:accent-indigo-400 transition-all"
            />

            <div className="flex justify-between text-[10px] text-zinc-500 font-mono">
              <span>
                {MIN_ROW_HEIGHT}px ({t('minLabel')})
              </span>
              <span>
                {DEFAULT_ROW_HEIGHT}px ({t('defaultLabel')})
              </span>
              <span>
                {MAX_ROW_HEIGHT}px ({t('maxLabel')})
              </span>
            </div>
          </div>

          {/* Preset Buttons */}
          <div className="flex items-center gap-1.5">
            {[
              { label: t('densityCompact'), val: 34 },
              { label: t('densityStandard'), val: 48 },
              { label: t('densitySpacious'), val: 64 },
            ].map((preset) => (
              <button
                key={preset.val}
                type="button"
                onClick={() => onRowHeightChange(preset.val)}
                className={`flex-1 py-1 rounded-md text-[11px] font-medium border transition-colors cursor-pointer ${
                  rowHeight === preset.val
                    ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40 shadow-sm'
                    : 'bg-zinc-800/60 text-zinc-400 border-zinc-700/60 hover:bg-zinc-800 hover:text-zinc-200'
                }`}
              >
                {preset.label} · {preset.val}px
              </button>
            ))}
          </div>

          {/* Minimum Warning Notice */}
          {rowHeight <= MIN_ROW_HEIGHT && (
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs animate-in fade-in motion-reduce:animate-none duration-150">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <div className="leading-relaxed">
                <span className="font-semibold text-amber-200">
                  {t('minRowHeightReached')} ({MIN_ROW_HEIGHT}px).
                </span>{' '}
                {t('minRowHeightDesc')}
              </div>
            </div>
          )}

          {/* 2-Row Sample Live Preview */}
          <div className="pt-2 border-t border-zinc-800/80 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">
                {t('livePreviewRows')}
              </span>
              <span className="text-[10px] text-zinc-500 font-mono">{rowHeight}px</span>
            </div>

            <div className="rounded-lg border border-zinc-800/90 bg-zinc-950/70 overflow-hidden shadow-inner">
              <table className="w-full text-left text-xs text-zinc-300 table-fixed">
                <thead className="bg-zinc-900/90 text-[10px] text-zinc-400 border-b border-zinc-800 uppercase tracking-wider">
                  <tr>
                    <th className="py-1 px-2.5 w-[34%]">{t('colTicker')}</th>
                    <th className="py-1 px-2 text-right w-[24%]">{t('colPriceShort')}</th>
                    <th className="py-1 px-2 text-right w-[24%]">Var.</th>
                    <th className="py-1 px-2 text-center w-[18%]">{t('colActions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60 font-sans">
                  {/* Sample Row 1: AAPL */}
                  <tr
                    style={{ height: `${rowHeight}px` }}
                    className="hover:bg-zinc-850/40 transition-colors"
                  >
                    <td className={`${cellPaddingClass} align-middle overflow-hidden`}>
                      <div className="flex flex-col min-w-0">
                        <span className="font-semibold text-white font-mono text-xs leading-none">
                          AAPL
                        </span>
                        {rowHeight > 42 && (
                          <span className="text-[10px] text-zinc-500 truncate leading-tight mt-0.5">
                            Apple Inc.
                          </span>
                        )}
                      </div>
                    </td>
                    <td
                      className={`${cellPaddingClass} text-right align-middle overflow-hidden font-mono text-xs text-white`}
                    >
                      $232.50
                    </td>
                    <td className={`${cellPaddingClass} text-right align-middle overflow-hidden`}>
                      <span className="inline-flex items-center gap-0.5 text-emerald-400 font-semibold font-mono text-xs">
                        <TrendingUp className="w-3 h-3 shrink-0" />
                        +1.45%
                      </span>
                    </td>
                    <td className={`${cellPaddingClass} text-center align-middle overflow-hidden`}>
                      <div className="inline-flex items-center justify-center gap-1 text-zinc-400">
                        <span className="p-1 rounded text-blue-400 bg-blue-500/10">
                          <FileText className="w-3 h-3" />
                        </span>
                        <span className="p-1 rounded text-zinc-500">
                          <Edit3 className="w-3 h-3" />
                        </span>
                      </div>
                    </td>
                  </tr>

                  {/* Sample Row 2: BME:MAP */}
                  <tr
                    style={{ height: `${rowHeight}px` }}
                    className="hover:bg-zinc-850/40 transition-colors"
                  >
                    <td className={`${cellPaddingClass} align-middle overflow-hidden`}>
                      <div className="flex flex-col min-w-0">
                        <span className="font-semibold text-white font-mono text-xs leading-none">
                          BME:MAP
                        </span>
                        {rowHeight > 42 && (
                          <span className="text-[10px] text-zinc-500 truncate leading-tight mt-0.5">
                            Mapfre S.A.
                          </span>
                        )}
                      </div>
                    </td>
                    <td
                      className={`${cellPaddingClass} text-right align-middle overflow-hidden font-mono text-xs text-white`}
                    >
                      2.38 €
                    </td>
                    <td className={`${cellPaddingClass} text-right align-middle overflow-hidden`}>
                      <span className="inline-flex items-center gap-0.5 text-rose-400 font-semibold font-mono text-xs">
                        <TrendingDown className="w-3 h-3 shrink-0" />
                        -0.62%
                      </span>
                    </td>
                    <td className={`${cellPaddingClass} text-center align-middle overflow-hidden`}>
                      <div className="inline-flex items-center justify-center gap-1 text-zinc-400">
                        <span className="p-1 rounded text-zinc-500">
                          <FileText className="w-3 h-3" />
                        </span>
                        <span className="p-1 rounded text-zinc-500">
                          <Edit3 className="w-3 h-3" />
                        </span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
