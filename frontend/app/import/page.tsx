import React from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { ImportView } from '@/components/ImportView';
import { AppHeader } from '@/components/AppHeader';
import { TranslatedText } from '@/context/LanguageContext';

export const metadata = {
  title: 'Import Watchlist | PortfolioMaster',
  description: 'Import your instruments and market quotes from CSV or Excel spreadsheets.',
};

export default function ImportPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* Top Navigation Bar */}
      <AppHeader />

      {/* Main Content Area */}
      <main id="main-content" className="flex-1 max-w-[1680px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        {/* Header section with page title */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link
                href="/"
                className="text-xs text-zinc-400 hover:text-emerald-400 inline-flex items-center gap-1 transition"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <TranslatedText tKey="backToWatchlist" />
              </Link>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
              <TranslatedText tKey="importPageTitle" />
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              <TranslatedText tKey="importPageDesc" />
            </p>
          </div>
        </div>

        {/* Import Interactive View Component */}
        <ImportView />
      </main>
    </div>
  );
}
