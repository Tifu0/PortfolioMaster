import React from 'react';

export default function BackupLoading() {
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
          <div className="h-7 w-56 bg-zinc-800 rounded-lg" />
          <div className="h-4 w-96 bg-zinc-850 rounded" />
        </div>

        {/* Content skeleton */}
        <div className="border border-zinc-800 rounded-2xl p-8 flex flex-col gap-6 bg-zinc-900/30">
          <div className="flex gap-4 border-b border-zinc-800 pb-4">
            <div className="h-6 w-36 bg-zinc-800 rounded" />
            <div className="h-6 w-44 bg-zinc-800/60 rounded" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-48 rounded-xl bg-zinc-900/60 border border-zinc-800/80 p-5 flex flex-col justify-between">
                <div className="w-10 h-10 rounded-lg bg-zinc-800" />
                <div className="h-5 w-28 bg-zinc-800 rounded" />
                <div className="h-4 w-full bg-zinc-800/60 rounded" />
                <div className="h-9 w-full bg-zinc-800 rounded-lg" />
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
