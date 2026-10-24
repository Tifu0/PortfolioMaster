'use client';

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from 'react';
import {
  supabase,
  signInWithEmail,
  signUpWithEmail,
  signOut as supabaseSignOut,
  Session,
  User,
} from '@/lib/supabase';

export interface AuthContextType {
  user: User | null;
  session: Session | null;
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

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const isAuthConfigured = Boolean(supabase);
  const [isLoading, setIsLoading] = useState<boolean>(isAuthConfigured);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [authMessage, setAuthMessage] = useState<string | null>(null);

  // Initialize session on mount
  useEffect(() => {
    if (!supabase) {
      return;
    }

    let isMounted = true;

    // 1. Fetch existing session
    supabase.auth.getSession().then(({ data: { session: initialSession } }) => {
      if (!isMounted) return;
      setSession(initialSession);
      setUser(initialSession?.user ?? null);
      setIsLoading(false);
    }).catch((err) => {
      console.warn('[Auth] Failed to load initial session:', err);
      if (isMounted) setIsLoading(false);
    });

    // 2. Listen to active auth-state changes & token refreshes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, currentSession) => {
        if (!isMounted) return;
        setSession(currentSession);
        setUser(currentSession?.user ?? null);
        setIsLoading(false);

        if (_event === 'SIGNED_IN') {
          setIsAuthModalOpen(false);
          setAuthMessage(null);
        } else if (_event === 'SIGNED_OUT') {
          setSession(null);
          setUser(null);
        }
      }
    );

    // 3. Listen to global auth-required signal from API client 401s
    const handleAuthRequired = (e: Event) => {
      const customEvent = e as CustomEvent<{ message?: string }>;
      const msg = customEvent.detail?.message || 'Identifícate para acceder a tu portafolio personal.';
      setAuthMessage(msg);
      setIsAuthModalOpen(true);
    };

    window.addEventListener('portfoliomaster:auth-required', handleAuthRequired);

    return () => {
      isMounted = false;
      subscription.unsubscribe();
      window.removeEventListener('portfoliomaster:auth-required', handleAuthRequired);
    };
  }, []);

  const openAuthModal = useCallback((message?: string) => {
    setAuthMessage(message || null);
    setIsAuthModalOpen(true);
  }, []);

  const closeAuthModal = useCallback(() => {
    setIsAuthModalOpen(false);
    setAuthMessage(null);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      const { data, error } = await signInWithEmail(email, password);
      if (error) {
        return { error };
      }
      setSession(data.session);
      setUser(data.user);
      setIsAuthModalOpen(false);
      setAuthMessage(null);
      return { error: null };
    } catch (err: unknown) {
      return { error: err instanceof Error ? err : new Error(String(err)) };
    }
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    try {
      const { data, error } = await signUpWithEmail(email, password);
      if (error) {
        return { error };
      }
      // If email confirmation is disabled, user & session are returned immediately
      if (data.session) {
        setSession(data.session);
        setUser(data.user);
        setIsAuthModalOpen(false);
        setAuthMessage(null);
        return { error: null, needsConfirmation: false };
      }
      return { error: null, needsConfirmation: true };
    } catch (err: unknown) {
      return { error: err instanceof Error ? err : new Error(String(err)) };
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await supabaseSignOut();
      setSession(null);
      setUser(null);
    } catch (err) {
      console.warn('[Auth] SignOut error:', err);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        isLoading,
        isAuthConfigured,
        isAuthModalOpen,
        authMessage,
        openAuthModal,
        closeAuthModal,
        signIn,
        signUp,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
