import React from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { BackupExportView } from '@/components/BackupExportView';
import { AppHeader } from '@/components/AppHeader';

export const metadata = {
  title: 'Copia de Seguridad y Exportación | PortfolioMaster',
  description: 'Exporta tu cartera a Excel, CSV o JSON y gestiona copias de seguridad de la base de datos.',
};

export default function BackupPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <AppHeader />

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
