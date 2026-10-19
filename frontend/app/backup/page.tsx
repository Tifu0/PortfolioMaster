import React from 'react';
import Link from 'next/link';
import { BarChart3, ArrowLeft } from 'lucide-react';
import { BackupExportView } from '@/components/BackupExportView';
import { HeaderNav } from '@/components/HeaderNav';

export const metadata = {
  title: 'Copia de Seguridad y Exportación | PortfolioMaster',
  description: 'Exporta tu cartera a Excel, CSV o JSON y gestiona copias de seguridad de la base de datos.',
};

export default function BackupPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-3 group">
              <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 group-hover:scale-105 transition">
                <BarChart3 className="w-5 h-5" />
              </div>
              <div>
                <span className="font-bold text-lg tracking-tight text-white flex items-center gap-2">
                  PortfolioMaster
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700/60 font-normal">
                    v1.0
                  </span>
                </span>
              </div>
            </Link>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-zinc-400 font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              FastAPI :8000
            </span>
          </div>
        </div>

        {/* Tab Navigation */}
        <HeaderNav />
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-[1680px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        {/* Header section with page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link
                href="/"
                className="text-xs text-zinc-400 hover:text-emerald-400 inline-flex items-center gap-1 transition"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Volver a la Watchlist
              </Link>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              Backup & Export
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              Exporta tu cartera completa en formato Excel, CSV o JSON, y descarga instantáneas atómicas o restaura la base de datos SQLite.
            </p>
          </div>
        </div>

        {/* Dedicated Backup & Export View */}
        <BackupExportView />
      </main>
    </div>
  );
}
