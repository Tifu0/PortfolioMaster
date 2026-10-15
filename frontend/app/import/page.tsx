import React from 'react';
import Link from 'next/link';
import { BarChart3, PlusCircle, Upload, ArrowLeft } from 'lucide-react';
import { ImportView } from '@/components/ImportView';

export const metadata = {
  title: 'Importar Watchlist | PortfolioMaster',
  description: 'Importa tus instrumentos y cotizaciones desde hojas de cálculo CSV o Excel.',
};

export default function ImportPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
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
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex gap-2 border-t border-zinc-900 overflow-x-auto">
          <Link
            href="/"
            className="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition"
          >
            <BarChart3 className="w-4 h-4" />
            Watchlist
          </Link>
          <Link
            href="/?add=1"
            className="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition"
            title="Añadir nuevo instrumento manualmente"
          >
            <PlusCircle className="w-4 h-4" />
            Añadir Valor
          </Link>
          <button
            className="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 border-emerald-500 text-emerald-400 bg-emerald-500/[0.03]"
          >
            <Upload className="w-4 h-4" />
            Importar
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
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
              Importar Archivo
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              Sube tus archivos CSV o Excel exportados para incorporar nuevos instrumentos al sistema.
            </p>
          </div>
        </div>

        {/* Import Interactive View Component */}
        <ImportView />
      </main>
    </div>
  );
}
