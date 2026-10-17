import React from 'react';
import { BarChart3 } from 'lucide-react';

export default function Loading() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col animate-pulse">
      {/* Header skeleton */}
      <header className="border-b border-zinc-800/80 bg-zinc-950/80 sticky top-0 z-50">
        <div className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-zinc-800 border border-zinc-700/60 flex items-center justify-center text-zinc-600">
              <BarChart3 className="w-5 h-5 opacity-40" />
            </div>
            <div className="h-5 w-32 bg-zinc-800 rounded" />
          </div>
          <div className="h-4 w-28 bg-zinc-800/60 rounded" />
        </div>
        <div className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 flex gap-4 border-t border-zinc-900 h-11 items-center">
          <div className="h-4 w-20 bg-zinc-800 rounded" />
          <div className="h-4 w-24 bg-zinc-850 rounded" />
          <div className="h-4 w-16 bg-zinc-850 rounded" />
        </div>
      </header>

      {/* Main skeleton content */}
      <main className="flex-1 max-w-[1680px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <div className="h-7 w-52 bg-zinc-800 rounded-lg" />
          <div className="h-4 w-96 bg-zinc-850 rounded" />
        </div>

        {/* 4 Skeleton Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-32 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 p-5 flex flex-col justify-between"
            >
              <div className="flex items-center justify-between">
                <div className="h-3 w-24 bg-zinc-800 rounded" />
                <div className="w-8 h-8 rounded-lg bg-zinc-800/70" />
              </div>
              <div className="h-8 w-28 bg-zinc-800 rounded" />
              <div className="h-3 w-3/4 bg-zinc-800/50 rounded" />
            </div>
          ))}
        </div>

        {/* Filter bar skeleton */}
        <div className="h-14 bg-zinc-900/80 border border-zinc-800/80 rounded-xl w-full flex items-center justify-between px-4">
          <div className="h-8 w-64 bg-zinc-800/60 rounded-lg" />
          <div className="flex gap-2">
            <div className="h-8 w-24 bg-zinc-800/60 rounded-lg" />
            <div className="h-8 w-32 bg-zinc-800/60 rounded-lg" />
          </div>
        </div>

        {/* Table skeleton */}
        <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4 flex flex-col gap-3">
          <div className="h-10 bg-zinc-850/60 rounded-lg w-full" />
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-12 bg-zinc-900/60 rounded-lg w-full flex items-center px-4 gap-4">
              <div className="h-4 w-16 bg-zinc-800 rounded" />
              <div className="h-4 w-36 bg-zinc-800/60 rounded" />
              <div className="h-4 w-20 bg-zinc-800/40 rounded ml-auto" />
              <div className="h-4 w-24 bg-zinc-800/60 rounded" />
              <div className="h-4 w-20 bg-zinc-800/50 rounded" />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
