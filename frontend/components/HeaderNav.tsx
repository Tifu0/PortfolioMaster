'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BarChart3, PlusCircle, Upload, Database } from 'lucide-react';

import { useLanguage } from '@/context/LanguageContext';

export function HeaderNav() {
  const pathname = usePathname();
  const { t } = useLanguage();

  const handleAddClick = (e: React.MouseEvent) => {
    if (pathname === '/') {
      e.preventDefault();
      window.history.pushState(null, '', '/?add=1');
      window.dispatchEvent(new CustomEvent('portfoliomaster:open-add'));
    }
  };

  const isWatchlist = pathname === '/';
  const isImport = pathname === '/import';
  const isBackup = pathname === '/backup';

  return (
    <nav aria-label={t('mainNavLabel')} className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 flex gap-1 sm:gap-2 border-t border-zinc-900 overflow-x-auto">
      <Link
        href="/"
        className={`flex items-center gap-2 px-3 sm:px-4 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap shrink-0 ${
          isWatchlist
            ? 'border-emerald-500 text-emerald-400 bg-emerald-500/[0.03]'
            : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
        }`}
      >
        <BarChart3 className="w-4 h-4 shrink-0" />
        {t('watchlist')}
      </Link>
      <Link
        href="/?add=1"
        onClick={handleAddClick}
        className="flex items-center gap-2 px-3 sm:px-4 py-3 text-sm font-medium border-b-2 border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition cursor-pointer whitespace-nowrap shrink-0"
        title={t('addInstrumentTooltip')}
      >
        <PlusCircle className="w-4 h-4 shrink-0" />
        {t('addInstrument')}
      </Link>
      <Link
        href="/import"
        className={`flex items-center gap-2 px-3 sm:px-4 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap shrink-0 ${
          isImport
            ? 'border-emerald-500 text-emerald-400 bg-emerald-500/[0.03]'
            : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
        }`}
      >
        <Upload className="w-4 h-4 shrink-0" />
        {t('import')}
      </Link>
      <Link
        href="/backup"
        className={`flex items-center gap-2 px-3 sm:px-4 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap shrink-0 ${
          isBackup
            ? 'border-emerald-500 text-emerald-400 bg-emerald-500/[0.03]'
            : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
        }`}
      >
        <Database className="w-4 h-4 shrink-0" />
        {t('backupExport')}
      </Link>
    </nav>
  );
}
