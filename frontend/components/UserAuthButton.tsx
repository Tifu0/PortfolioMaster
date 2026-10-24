'use client';

import React from 'react';
import { useAuth } from '@/context/AuthContext';
import { LogIn, LogOut, User as UserIcon } from 'lucide-react';

export function UserAuthButton() {
  const { user, isLoading, isAuthConfigured, openAuthModal, signOut } = useAuth();

  if (isLoading) {
    return <div className="w-24 h-8 bg-zinc-900 border border-zinc-800 rounded-lg animate-pulse" />;
  }

  if (!isAuthConfigured) {
    return null; // Gracefully hidden when auth is not configured in local development
  }

  if (user) {
    const displayEmail = user.email || 'Usuario';
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-zinc-900 border border-zinc-800 rounded-lg text-xs font-mono text-zinc-300">
          <UserIcon className="w-3.5 h-3.5 text-emerald-400" />
          <span className="max-w-[120px] truncate">{displayEmail}</span>
        </div>
        <button
          type="button"
          onClick={() => signOut()}
          className="flex items-center gap-1 px-2.5 py-1.5 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 text-zinc-400 hover:text-zinc-200 text-xs font-medium rounded-lg transition"
          title="Cerrar sesión"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Salir</span>
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => openAuthModal()}
      className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-400 hover:text-emerald-300 text-xs font-semibold rounded-lg transition shadow-sm"
    >
      <LogIn className="w-3.5 h-3.5" />
      <span>Iniciar Sesión</span>
    </button>
  );
}
