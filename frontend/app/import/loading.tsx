import React from 'react';
import { Upload } from 'lucide-react';

export default function ImportLoading() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col animate-pulse">
      {/* Header skeleton */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 sticky top-0 z-50">
        <div className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-zinc-800 border border-zinc-700/60" />
            <div className="h-5 w-32 bg-zinc-800 rounded" />
          </div>
          <div className="h-4 w-28 bg-zinc-800/60 rounded" />
        </div>
      </header>

      {/* Main content skeleton */}
      <main className="flex-1 max-w-[1680px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <div className="h-7 w-48 bg-zinc-800 rounded-lg" />
          <div className="h-4 w-96 bg-zinc-850 rounded" />
        </div>

        {/* Dropzone skeleton */}
        <div className="border-2 border-dashed border-zinc-800 rounded-2xl p-12 flex flex-col items-center justify-center gap-4 bg-zinc-900/30">
          <div className="w-14 h-14 rounded-2xl bg-zinc-800/80 flex items-center justify-center text-zinc-600">
            <Upload className="w-7 h-7 opacity-40" />
          </div>
          <div className="h-5 w-64 bg-zinc-800 rounded" />
          <div className="h-4 w-48 bg-zinc-800/60 rounded" />
        </div>
      </main>
    </div>
  );
}
