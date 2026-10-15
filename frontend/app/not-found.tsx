import React from 'react';
import Link from 'next/link';
import { BarChart3, Home } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-zinc-900/90 border border-zinc-800 rounded-2xl p-8 shadow-2xl backdrop-blur flex flex-col items-center text-center">
        <div className="w-14 h-14 rounded-2xl bg-zinc-800/80 border border-zinc-700/60 flex items-center justify-center text-emerald-400 mb-6">
          <BarChart3 className="w-7 h-7" />
        </div>

        <span className="text-4xl font-extrabold font-mono text-zinc-500">404</span>
        <h1 className="mt-2 text-xl font-bold tracking-tight text-white">
          Página no encontrada
        </h1>
        <p className="mt-2 text-sm text-zinc-400 leading-relaxed">
          La ruta a la que intentas acceder no existe en PortfolioMaster.
        </p>

        <div className="mt-6">
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-900/20"
          >
            <Home className="w-4 h-4" />
            Volver a la Watchlist
          </Link>
        </div>
      </div>
    </div>
  );
}
