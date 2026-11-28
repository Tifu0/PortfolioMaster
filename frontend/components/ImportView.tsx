'use client';

// 'use client' is required here because file drag-and-drop, file upload state,
// validation preview, and committing instruments require interactive client-side
// React state (useState, useRef, useEffect) and event listeners.

import React, { useState, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  UploadCloud,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Loader2,
  ArrowRight,
  Download,
  Trash2,
  Table as TableIcon,
  RefreshCw,
} from 'lucide-react';
import { previewImport, confirmImport } from '@/lib/api';
import { usePortfolioDataOptional } from '@/context/PortfolioContext';
import { useLanguage } from '@/context/LanguageContext';
import { formatCurrency } from '@/lib/formatters';
import type { ImportPreviewResponse, Instrument } from '@/lib/types';

export function ImportView() {
  const portfolioContext = usePortfolioDataOptional();
  const router = useRouter();
  const { language, t } = useLanguage();

  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successCount, setSuccessCount] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (selectedFile: File) => {
    const ext = selectedFile.name.split('.').pop()?.toLowerCase();
    if (ext !== 'csv' && ext !== 'xlsx') {
      setErrorMessage(t('unsupportedFileFormat'));
      return;
    }
    setFile(selectedFile);
    setPreview(null);
    setErrorMessage(null);
    setSuccessCount(null);
  };

  const handleAnalyze = async () => {
    if (!file) return;
    setIsAnalyzing(true);
    setErrorMessage(null);

    try {
      const result = await previewImport(file, file.name);
      setPreview(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(t('errorAnalyzingFile', { error: msg }));
      setPreview(null);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleConfirm = async () => {
    if (!preview || preview.instruments.length === 0) return;
    setIsCommitting(true);
    setErrorMessage(null);

    try {
      // Send instruments dictionary matching backend API expectations (CRITICAL FIX: Bug 5 - includes YTD references)
      const instrumentsToCommit = preview.instruments.map((inst: Instrument) => ({
        user_ticker: inst.user_ticker,
        provider_symbol: inst.provider_symbol,
        exchange: inst.exchange,
        currency: inst.currency,
        company_name: inst.company_name,
        analysis_date: inst.analysis_date,
        analysis_reference_price: inst.analysis_reference_price,
        start_of_year_date: inst.start_of_year_date,
        start_of_year_price: inst.start_of_year_price,
        target_price: inst.target_price,
        comment: inst.comment,
        active: inst.active,
      }));

      const res = await confirmImport(instrumentsToCommit);
      if (res.errors && res.errors.length > 0) {
        setErrorMessage(t('importedWithNotices', { count: res.committed, notices: res.errors.join(', ') }));
      }
      setSuccessCount(res.committed);
      setPreview(null);
      setFile(null);

      // Invalidate and refresh portfolio state across routes
      if (portfolioContext) {
        await portfolioContext.refreshPortfolioData({ silent: true });
      }
      try {
        router.refresh();
      } catch {
        // Safe fallback in test environments
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMessage(t('errorConfirmingImport', { error: msg }));
    } finally {
      setIsCommitting(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPreview(null);
    setErrorMessage(null);
    setSuccessCount(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const downloadSampleCsv = () => {
    const todayStr = new Date().toISOString().split('T')[0];
    const csvContent =
      'user_ticker,company_name,currency,target_price,analysis_reference_price,analysis_date,comment\n' +
      `AAPL,Apple Inc.,USD,220.00,185.00,${todayStr},Ecosystem and services market leader\n` +
      `BME:SAN,Banco Santander,EUR,5.50,4.25,${todayStr},Attractive valuation and dividend yield\n` +
      `MSFT,Microsoft Corp.,USD,480.00,420.00,${todayStr},Cloud growth and AI innovation leadership\n` +
      `LON:AZN,AstraZeneca PLC,GBP,140.00,120.00,${todayStr},Strong oncology drug pipeline\n`;

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', 'watchlist_template.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Success Notification Banner */}
      {successCount !== null && (
        <div className="p-6 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-in fade-in motion-reduce:animate-none">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
              <CheckCircle2 className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-semibold text-emerald-300 text-base">
                {t('importSuccessTitle')}
              </h3>
              <p className="text-xs text-emerald-400/80 mt-0.5">
                {t('importSuccessDesc', { count: successCount })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleReset}
              className="px-3.5 py-2 text-xs font-medium text-zinc-300 hover:text-white bg-zinc-800 hover:bg-zinc-700 rounded-xl transition"
            >
              {t('importAnotherFile')}
            </button>
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-emerald-950 bg-emerald-400 hover:bg-emerald-300 rounded-xl transition shadow-sm"
            >
              {t('viewInWatchlist')}
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      )}

      {/* Error Banner */}
      {errorMessage && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-3">
          <XCircle className="w-5 h-5 shrink-0 text-rose-400" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Step 1: Upload Card */}
      {!preview && successCount === null && (
        <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-6 sm:p-8 backdrop-blur flex flex-col gap-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                <FileSpreadsheet className="w-5 h-5 text-emerald-400" />
                {t('uploadSpreadsheetTitle')}
              </h2>
              <p className="text-xs text-zinc-400 mt-1">
                {t('uploadSpreadsheetDesc')}
              </p>
            </div>

            <button
              onClick={downloadSampleCsv}
              className="inline-flex items-center gap-2 text-xs font-medium text-zinc-300 hover:text-white px-3.5 py-2 rounded-xl bg-zinc-800/80 hover:bg-zinc-800 border border-zinc-700/60 transition self-start sm:self-auto"
              title={t('downloadCsvTemplateTitle')}
            >
              <Download className="w-3.5 h-3.5 text-emerald-400" />
              {t('downloadCsvTemplate')}
            </button>
          </div>

          {/* Drag & Drop Zone */}
          <div
            role="button"
            tabIndex={0}
            aria-label={t('uploadSpreadsheetAria')}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            className={`cursor-pointer border-2 border-dashed rounded-2xl p-8 sm:p-12 text-center transition flex flex-col items-center justify-center gap-4 focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
              isDragging
                ? 'border-emerald-500 bg-emerald-500/5'
                : 'border-zinc-800 hover:border-zinc-700 bg-zinc-950/40 hover:bg-zinc-950/60'
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".csv,.xlsx"
              aria-label={t('selectSpreadsheetAria')}
              className="hidden"
            />

            <div className="w-14 h-14 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-400 group-hover:text-emerald-400">
              <UploadCloud className="w-7 h-7 text-emerald-400" />
            </div>

            <div className="flex flex-col gap-1 max-w-sm">
              <span className="text-sm font-semibold text-zinc-200">
                {t('dragDropSpreadsheet')}
              </span>
              <span className="text-xs text-zinc-500">
                {t('supportsSpreadsheetFormats')}
              </span>
            </div>
          </div>

          {/* Selected File Details */}
          {file && (
            <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800 flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
                  <FileSpreadsheet className="w-5 h-5" />
                </div>
                <div className="min-w-0 truncate">
                  <span className="text-sm font-medium text-white block truncate">
                    {file.name}
                  </span>
                  <span className="text-xs text-zinc-500 font-mono">
                    {(file.size / 1024).toFixed(1)} KB
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleReset();
                  }}
                  className="p-2 text-zinc-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition"
                  title={t('removeFile')}
                  aria-label={t('removeSelectedFileAria')}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={handleAnalyze}
                  disabled={isAnalyzing}
                  className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-emerald-950 bg-emerald-400 hover:bg-emerald-300 disabled:opacity-50 rounded-xl transition shadow-sm"
                >
                  {isAnalyzing ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                      {t('analyzing')}
                    </>
                  ) : (
                    <>
                      <RefreshCw className="w-3.5 h-3.5" />
                      {t('analyzeAndValidate')}
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step 2: Review Preview & Validation Inconsistencies */}
      {preview && (
        <div className="flex flex-col gap-6 animate-in fade-in motion-reduce:animate-none">
          {/* Header & Status Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-4">
              <span className="text-xs text-zinc-400 font-medium">{t('validInstruments')}</span>
              <div className="mt-2 text-2xl font-bold font-mono text-emerald-400 flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                {preview.valid_count}
              </div>
            </div>

            <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-4">
              <span className="text-xs text-zinc-400 font-medium">{t('warningsDuplicates')}</span>
              <div className="mt-2 text-2xl font-bold font-mono text-amber-400 flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-amber-400" />
                {preview.warnings.length}
              </div>
            </div>

            <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-4">
              <span className="text-xs text-zinc-400 font-medium">{t('unresolvedSymbols')}</span>
              <div className="mt-2 text-2xl font-bold font-mono text-orange-400 flex items-center gap-2">
                <HelpCircle className="w-5 h-5 text-orange-400" />
                {preview.unresolved.length}
              </div>
            </div>

            <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-4">
              <span className="text-xs text-zinc-400 font-medium">{t('rowErrors')}</span>
              <div className="mt-2 text-2xl font-bold font-mono text-rose-400 flex items-center gap-2">
                <XCircle className="w-5 h-5 text-rose-400" />
                {preview.errors.length}
              </div>
            </div>
          </div>

          {/* Warning: Unresolved Symbols */}
          {preview.unresolved.length > 0 && (
            <div className="p-4 rounded-xl bg-orange-500/10 border border-orange-500/30 text-xs text-orange-300">
              <div className="flex items-center gap-2 font-semibold">
                <HelpCircle className="w-4 h-4 text-orange-400" />
                <span>{t('unresolvedHeader', { count: preview.unresolved.length })}</span>
              </div>
              <p className="mt-1 text-orange-300/80">
                {t('unresolvedDesc')}
              </p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {preview.unresolved.map((sym, idx) => (
                  <span key={idx} className="px-2 py-0.5 rounded font-mono bg-orange-500/20 text-orange-200 border border-orange-500/30">
                    {typeof sym === 'string' ? sym : JSON.stringify(sym)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Warning: Duplicates */}
          {preview.warnings.length > 0 && (
            <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-300">
              <div className="flex items-center gap-2 font-semibold">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>{t('duplicateNoticesHeader', { count: preview.warnings.length })}</span>
              </div>
              <ul className="mt-2 list-disc list-inside space-y-1 text-amber-300/80">
                {preview.warnings.map((w, idx) => (
                  <li key={idx}>{typeof w === 'string' ? w : JSON.stringify(w)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Errors: Row Parsing */}
          {preview.errors.length > 0 && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300">
              <div className="flex items-center gap-2 font-semibold">
                <XCircle className="w-4 h-4 text-rose-400" />
                <span>{t('rowErrorsHeader', { count: preview.errors.length })}</span>
              </div>
              <ul className="mt-2 list-disc list-inside space-y-1 text-rose-300/80">
                {preview.errors.map((e, idx) => (
                  <li key={idx}>{typeof e === 'string' ? e : JSON.stringify(e)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Validated Instruments Preview Table */}
          {preview.instruments.length > 0 && (
            <div className="rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-4 sm:p-6 backdrop-blur flex flex-col gap-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <TableIcon className="w-4 h-4 text-emerald-400 shrink-0" />
                    {t('validatedPreviewHeader', { count: preview.instruments.length })}
                  </h3>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    {t('validatedPreviewDesc')}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={handleReset}
                    className="px-3.5 py-2 text-xs font-medium text-zinc-400 hover:text-white bg-zinc-800 hover:bg-zinc-700 rounded-xl transition"
                  >
                    {t('discard')}
                  </button>
                  <button
                    onClick={handleConfirm}
                    disabled={isCommitting}
                    className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-emerald-950 bg-emerald-400 hover:bg-emerald-300 disabled:opacity-50 rounded-xl transition shadow-sm"
                  >
                    {isCommitting ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                        {t('saving')}
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        {t('confirmImportCount', { count: preview.instruments.length })}
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto rounded-xl border border-zinc-800">
                <table className="w-full text-left text-xs border-collapse">
                  <thead className="bg-zinc-950/80 text-zinc-400 font-medium border-b border-zinc-800">
                    <tr>
                      <th className="py-3 px-4">{t('colTicker')}</th>
                      <th className="py-3 px-4">{t('colCompany')}</th>
                      <th className="py-3 px-4">{t('colExchange')}</th>
                      <th className="py-3 px-4">{t('colCurrency')}</th>
                      <th className="py-3 px-4 text-right">{t('colAnalysisPrice')}</th>
                      <th className="py-3 px-4 text-right">{t('colTargetPrice')}</th>
                      <th className="py-3 px-4">{t('colComments')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60 bg-zinc-900/40">
                    {preview.instruments.map((inst, idx) => (
                      <tr key={idx} className="hover:bg-zinc-800/30 transition">
                        <td className="py-2.5 px-4 font-mono font-bold text-white">
                          {inst.user_ticker}
                          {inst.provider_symbol && inst.provider_symbol !== inst.user_ticker && (
                            <span className="ml-1.5 text-[10px] font-normal text-zinc-500">
                              ({inst.provider_symbol})
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 px-4 text-zinc-200">
                          {inst.company_name}
                        </td>
                        <td className="py-2.5 px-4">
                          <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-300 border border-zinc-700/60">
                            {String(inst.exchange)}
                          </span>
                        </td>
                        <td className="py-2.5 px-4 font-mono text-zinc-300">
                          {inst.currency}
                        </td>
                        <td className="py-2.5 px-4 text-right font-mono text-zinc-300">
                          {formatCurrency(inst.analysis_reference_price, inst.currency, language)}
                        </td>
                        <td className="py-2.5 px-4 text-right font-mono text-zinc-300">
                          {formatCurrency(inst.target_price, inst.currency, language)}
                        </td>
                        <td className="py-2.5 px-4 text-zinc-400 truncate max-w-xs" title={inst.comment}>
                          {inst.comment || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
