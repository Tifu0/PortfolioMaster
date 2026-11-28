'use client';

import { createContext, use, useCallback, useEffect, useEffectEvent, useMemo, useRef, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { clearApiClientCache } from '@/lib/api';
import { isAuthConfigured, supabaseUrl, type AuthUser } from '@/lib/supabase';
import { useLanguage } from '@/context/LanguageContext';

export interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthConfigured: boolean;
  isAuthModalOpen: boolean;
  authMessage: string | null;
  openAuthModal: (message?: string) => void;
  closeAuthModal: () => void;
  signIn: (email: string, password: string) => Promise<{ error: Error | null }>;
  signUp: (email: string, password: string) => Promise<{ error: Error | null; needsConfirmation?: boolean }>;
  signOut: () => Promise<void>;
}

type AuthAction = { action: 'signIn' | 'signUp'; email: string; password: string } | { action: 'signOut' };
type AuthResult = { user: AuthUser | null; needsConfirmation?: boolean; error?: string };

const AuthContext = createContext<AuthContextType | null>(null);

async function requestAuth(action: AuthAction): Promise<AuthResult> {
  const response = await fetch('/api/auth', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(action),
  });
  const result: AuthResult = await response.json();
  if (!response.ok) throw new Error(result.error || 'Authentication request failed.');
  return result;
}

export function AuthProvider({ children, initialUser = null }: { children: ReactNode; initialUser?: AuthUser | null }) {
  const { t } = useLanguage();
  const router = useRouter();
  const [previousInitialUser, setPreviousInitialUser] = useState(initialUser);
  const [user, setUser] = useState(initialUser);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authMessage, setAuthMessage] = useState<string | null>(null);
  const authChannel = useRef<BroadcastChannel | null>(null);

  if (previousInitialUser?.id !== initialUser?.id || previousInitialUser?.email !== initialUser?.email) {
    setPreviousInitialUser(initialUser);
    setUser(initialUser);
  }

  const openAuthModal = useCallback((message?: string) => {
    setAuthMessage(message || null);
    setIsAuthModalOpen(true);
  }, []);

  const closeAuthModal = useCallback(() => {
    setIsAuthModalOpen(false);
    setAuthMessage(null);
  }, []);

  const updateUser = useCallback((nextUser: AuthUser | null, broadcast = false) => {
    clearApiClientCache();
    setUser(nextUser);
    if (broadcast) authChannel.current?.postMessage('session-changed');
    router.refresh();
  }, [router]);

  const handleAuthRequired = useEffectEvent((event: Event) => {
    if (user) updateUser(null);
    const { detail } = event as CustomEvent<{ message?: string }>;
    openAuthModal(detail?.message || t('authRequiredMessage'));
  });

  const handleRemoteSessionChange = useEffectEvent((event: MessageEvent) => {
    if (event.data !== 'session-changed') return;
    clearApiClientCache();
    setUser(null);
    window.location.reload();
  });

  useEffect(() => {
    if (!isAuthConfigured || !supabaseUrl) return;

    // Remove credentials left by the previous browser SDK without reading them.
    try {
      const project = new URL(supabaseUrl).hostname.split('.')[0];
      const legacyKey = `sb-${project}-auth-token`;
      localStorage.removeItem(legacyKey);
      localStorage.removeItem(`${legacyKey}-code-verifier`);
    } catch {
      // Storage may be disabled by browser policy.
    }

    const listener = (event: Event) => handleAuthRequired(event);
    window.addEventListener('portfoliomaster:auth-required', listener);
    const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('portfoliomaster:auth');
    if (channel) {
      channel.onmessage = (event) => handleRemoteSessionChange(event);
      authChannel.current = channel;
    }
    return () => {
      channel?.close();
      authChannel.current = null;
      window.removeEventListener('portfoliomaster:auth-required', listener);
    };
  }, []);

  const authenticate = useCallback(async (action: 'signIn' | 'signUp', email: string, password: string) => {
    try {
      const { user: authenticatedUser, needsConfirmation } = await requestAuth({ action, email, password });
      if (authenticatedUser) {
        closeAuthModal();
        updateUser(authenticatedUser, true);
      }
      return { error: null, needsConfirmation };
    } catch (error) {
      return { error: error instanceof Error ? error : new Error(String(error)) };
    }
  }, [closeAuthModal, updateUser]);

  const signIn = useCallback((email: string, password: string) => authenticate('signIn', email, password), [authenticate]);
  const signUp = useCallback((email: string, password: string) => authenticate('signUp', email, password), [authenticate]);

  const signOut = useCallback(async () => {
    try {
      await requestAuth({ action: 'signOut' });
      updateUser(null, true);
    } catch (error) {
      console.warn('[Auth] Sign-out request failed:', error);
    }
  }, [updateUser]);

  const value = useMemo(() => ({
    user, isLoading: false, isAuthConfigured, isAuthModalOpen, authMessage,
    openAuthModal, closeAuthModal, signIn, signUp, signOut,
  }), [user, isAuthModalOpen, authMessage, openAuthModal, closeAuthModal, signIn, signUp, signOut]);

  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthContextType {
  const context = use(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}

export function useAuthOptional(): AuthContextType | null {
  return use(AuthContext);
}
