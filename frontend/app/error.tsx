'use client';

// 'use client' is required for Next.js App Router error boundaries (error.tsx).

import React, { useEffect } from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import Link from 'next/link';
import { useLanguage } from '@/context/LanguageContext';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const { t } = useLanguage();

  useEffect(() => {
    // Log unexpected errors for client monitoring
    console.error('Unhandled PortfolioMaster runtime error:', error);
  }, [error]);

  const isTranslationError = Boolean(
    error?.message &&
      (error.message.includes('removeChild') ||
        error.message.includes('insertBefore') ||
        error.message.includes('hijo de este nodo') ||
        error.message.includes('not a child of this node'))
  );

  return (
    <main id="main-content" className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-4">
      <div className="w-full max-w-lg bg-zinc-900/90 border border-zinc-800 rounded-2xl p-8 shadow-2xl backdrop-blur flex flex-col items-center text-center">
        <div className="w-14 h-14 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-6">
          <AlertTriangle className="w-7 h-7" />
        </div>

        <h2 className="text-xl font-bold tracking-tight text-white">
          {t('errorTitle')}
        </h2>

        {isTranslationError ? (
          <div className="mt-3 text-left p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-200 text-xs leading-relaxed">
            <p className="font-semibold mb-1 text-amber-300">
              {t('translationErrorTitle')}
            </p>
            <p className="text-zinc-300">
              {t('translationErrorDesc')}
            </p>
            <p className="mt-2 text-amber-300/90">
              💡 <strong>{t('solutionLabel')}</strong> {t('translationErrorHint')}
            </p>
          </div>
        ) : (
          <p className="mt-2 text-sm text-zinc-400 leading-relaxed max-w-md">
            {error.message || t('errorDefaultMsg')}
          </p>
        )}

        {error.digest && (
          <span className="mt-3 text-[11px] font-mono px-2 py-1 rounded bg-zinc-800/80 text-zinc-500 border border-zinc-700/60">
            Digest: {error.digest}
          </span>
        )}

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3 w-full">
          <button
            onClick={() => {
              if (isTranslationError) {
                window.location.reload();
              } else {
                reset();
              }
            }}
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-900/20"
          >
            <RefreshCw className="w-4 h-4" />
            {t('retry')}
          </button>
          <Link
            href="/"
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-750 border border-zinc-700 transition-colors"
          >
            <Home className="w-4 h-4" />
            {t('returnHome')}
          </Link>
        </div>
      </div>
    </main>
  );
}
