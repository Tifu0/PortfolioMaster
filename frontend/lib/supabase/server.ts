import { createServerClient, type CookieMethodsServer } from '@supabase/ssr';
import { cookies } from 'next/headers';
import type { NextRequest, NextResponse } from 'next/server';
import { cache } from 'react';
import { supabaseKey, supabaseUrl, type AuthUser } from '../supabase';

const cookieOptions = {
  httpOnly: true,
  secure: true,
  sameSite: 'lax' as const,
  path: '/',
};

function createSupabase(store: CookieMethodsServer) {
  if (!supabaseUrl || !supabaseKey) return null;
  return createServerClient(supabaseUrl, supabaseKey, { cookieOptions, cookies: store });
}

/** Read the session after Proxy has refreshed it, then verify the token before trusting claims. */
export const getServerAuth = cache(async (): Promise<{ user: AuthUser | null; accessToken: string | null }> => {
  if (!supabaseUrl || !supabaseKey) return { user: null, accessToken: null };
  const store = await cookies();
  const supabase = createSupabase({ getAll: () => store.getAll(), setAll() {} });
  if (!supabase) return { user: null, accessToken: null };

  const { data: { session } } = await supabase.auth.getSession();
  if (!session) return { user: null, accessToken: null };
  const { data, error } = await supabase.auth.getClaims(session.access_token);
  if (error || !data?.claims.sub) return { user: null, accessToken: null };

  const { sub, email } = data.claims;
  return { user: { id: sub, email }, accessToken: session.access_token };
});

/** Collect cookie updates for the exact response returned by a handler or Proxy. */
export function createRequestSupabase(request: NextRequest) {
  type CookieUpdate = Parameters<NonNullable<CookieMethodsServer['setAll']>>[0][number];
  const updates = new Map<string, CookieUpdate>();
  const headers = new Headers();
  const supabase = createSupabase({
    getAll: () => request.cookies.getAll(),
    setAll(cookiesToSet, cacheHeaders) {
      for (const cookie of cookiesToSet) {
        updates.set(cookie.name, cookie);
        request.cookies.set(cookie.name, cookie.value);
      }
      for (const [name, value] of Object.entries(cacheHeaders ?? {})) headers.set(name, value);
    },
  });

  return {
    supabase,
    applyCookies<T extends NextResponse>(response: T): T {
      for (const { name, value, options } of updates.values()) {
        response.cookies.set(name, value, { ...options, ...cookieOptions });
      }
      headers.forEach((value, name) => response.headers.set(name, value));
      response.headers.set('Cache-Control', 'private, no-store');
      return response;
    },
  };
}
