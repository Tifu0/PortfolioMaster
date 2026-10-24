'use client';

import React from 'react';
import {
  Download,
  Database,
  FileSpreadsheet,
  FileText,
  FileJson,
  Loader2,
  FileDown,
} from 'lucide-react';

interface ExportSectionProps {
  onExport: (format: 'csv' | 'excel' | 'json') => Promise<void>;
  onDownloadDb: () => Promise<void>;
  exportingFormat: string | null;
  downloadingDb: boolean;
}

export function ExportSection({
  onExport,
  onDownloadDb,
  exportingFormat,
  downloadingDb,
}: ExportSectionProps) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Download className="w-4 h-4 text-emerald-400" />
          Export Watchlist Data
        </h3>
        <p className="text-xs text-zinc-400 mt-1">
          Download your current watchlist instruments, target prices, and calculated metrics in your preferred format.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* CSV Export Card */}
        <div className="p-5 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700 transition flex flex-col justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0 border border-emerald-500/20">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-zinc-200 text-sm">CSV Format</h4>
              <p className="text-xs text-zinc-400 mt-0.5">
                Comma-separated values spreadsheet, universally compatible with Excel and Google Sheets.
              </p>
            </div>
          </div>
          <button
            onClick={() => onExport('csv')}
            disabled={Boolean(exportingFormat)}
            className="w-full inline-flex items-center justify-center gap-2 px-3.5 py-2 text-xs font-medium text-zinc-200 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded-xl transition border border-zinc-700/60"
          >
            {exportingFormat === 'csv' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <FileDown className="w-3.5 h-3.5 text-emerald-400" />
                Download CSV
              </>
            )}
          </button>
        </div>

        {/* Excel Export Card */}
        <div className="p-5 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700 transition flex flex-col justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-teal-500/10 text-teal-400 flex items-center justify-center shrink-0 border border-teal-500/20">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-zinc-200 text-sm">Excel (.xlsx)</h4>
              <p className="text-xs text-zinc-400 mt-0.5">
                Formatted native Excel workbook with styled headers and tabular numeric columns.
              </p>
            </div>
          </div>
          <button
            onClick={() => onExport('excel')}
            disabled={Boolean(exportingFormat)}
            className="w-full inline-flex items-center justify-center gap-2 px-3.5 py-2 text-xs font-medium text-zinc-200 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded-xl transition border border-zinc-700/60"
          >
            {exportingFormat === 'excel' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <FileDown className="w-3.5 h-3.5 text-teal-400" />
                Download Excel
              </>
            )}
          </button>
        </div>

        {/* JSON Export Card */}
        <div className="p-5 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700 transition flex flex-col justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/10 text-cyan-400 flex items-center justify-center shrink-0 border border-cyan-500/20">
              <FileJson className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-zinc-200 text-sm">JSON Format</h4>
              <p className="text-xs text-zinc-400 mt-0.5">
                Structured machine-readable snapshot, perfect for backups and programmatic migrations.
              </p>
            </div>
          </div>
          <button
            onClick={() => onExport('json')}
            disabled={Boolean(exportingFormat)}
            className="w-full inline-flex items-center justify-center gap-2 px-3.5 py-2 text-xs font-medium text-zinc-200 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded-xl transition border border-zinc-700/60"
          >
            {exportingFormat === 'json' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <FileDown className="w-3.5 h-3.5 text-cyan-400" />
                Download JSON
              </>
            )}
          </button>
        </div>
      </div>

      {/* Raw SQLite Database Backup Download */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-zinc-900/80 to-zinc-900/40 border border-zinc-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center shrink-0 border border-purple-500/20">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <h4 className="font-semibold text-zinc-100 text-sm">Raw Database Snapshot (.db)</h4>
            <p className="text-xs text-zinc-400 mt-0.5">
              Complete raw database binary file containing all schema definitions, instruments, and quotes.
            </p>
          </div>
        </div>
        <button
          onClick={onDownloadDb}
          disabled={downloadingDb}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold text-purple-950 bg-purple-400 hover:bg-purple-300 disabled:opacity-50 rounded-xl transition shadow-sm shrink-0"
        >
          {downloadingDb ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Generating Snapshot...
            </>
          ) : (
            <>
              <Download className="w-3.5 h-3.5" />
              Download .db File
            </>
          )}
        </button>
      </div>
    </div>
  );
}
