import { createClient, SupabaseClient, Session, User } from '@supabase/supabase-js';

export type { Session, User };

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/**
 * Singleton Supabase client for client-side authentication, subscriptions and queries.
 * Configured with secure session persistence in localStorage and automatic token refresh.
 */
export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      })
    : null;

/**
 * Obtain the active Supabase JWT Bearer access token.
 * Returns null if unauthenticated or Supabase is not configured.
 */
export async function getAuthToken(): Promise<string | null> {
  if (!supabase) return null;
  try {
    const { data: { session }, error } = await supabase.auth.getSession();
    if (error || !session) return null;
    return session.access_token;
  } catch {
    return null;
  }
}

/**
 * Get the current authenticated user or null.
 */
export async function getCurrentUser(): Promise<User | null> {
  if (!supabase) return null;
  try {
    const { data: { user }, error } = await supabase.auth.getUser();
    if (error || !user) return null;
    return user;
  } catch {
    return null;
  }
}

/**
 * Check if Supabase client is configured and available.
 */
export function isAuthAvailable(): boolean {
  return Boolean(supabase);
}

/**
 * Sign in using email and password.
 */
export async function signInWithEmail(email: string, password: string) {
  if (!supabase) {
    throw new Error('Supabase client is not configured. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.');
  }
  return supabase.auth.signInWithPassword({ email, password });
}

/**
 * Register a new user account with email and password.
 */
export async function signUpWithEmail(email: string, password: string) {
  if (!supabase) {
    throw new Error('Supabase client is not configured. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.');
  }
  return supabase.auth.signUp({ email, password });
}

/**
 * Sign out the currently active session.
 */
export async function signOut() {
  if (!supabase) return;
  return supabase.auth.signOut();
}
