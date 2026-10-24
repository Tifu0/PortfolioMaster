'use client';

import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="es" className="h-full bg-zinc-950 text-zinc-100">
      <body className="h-full flex items-center justify-center p-4">
        <div className="w-full max-w-lg bg-zinc-900/90 border border-zinc-800 rounded-2xl p-8 shadow-2xl backdrop-blur flex flex-col items-center text-center">
          <div className="w-14 h-14 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-6">
            <AlertTriangle className="w-7 h-7" />
          </div>
          <h2 className="text-xl font-bold tracking-tight text-white">
            Error Crítico de Aplicación
          </h2>
          <p className="mt-2 text-sm text-zinc-400 leading-relaxed max-w-md">
            Se produjo un error no recuperable en el contenedor raíz del portfolio.
          </p>
          {error.digest && (
            <span className="mt-3 text-[11px] font-mono px-2 py-1 rounded bg-zinc-800/80 text-zinc-500 border border-zinc-700/60">
              Digest: {error.digest}
            </span>
          )}
          <div className="mt-8 flex justify-center w-full">
            <button
              onClick={() => reset()}
              className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-900/20 cursor-pointer"
            >
              <RefreshCw className="w-4 h-4" />
              Reiniciar Aplicación
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
