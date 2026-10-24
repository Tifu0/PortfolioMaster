'use client';

import React from 'react';
import Link from 'next/link';
import { BarChart3 } from 'lucide-react';
import { HeaderNav } from './HeaderNav';
import { UserAuthButton } from './UserAuthButton';

export function AppHeader() {
  return (
    <header className="border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-[1680px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
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

        <div className="flex items-center gap-3">
          <UserAuthButton />
          <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-zinc-400 font-mono">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            FastAPI
          </span>
        </div>
      </div>

      {/* Tab Navigation */}
      <HeaderNav />
    </header>
  );
}
