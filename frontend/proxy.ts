import { NextResponse, type NextRequest } from 'next/server';
import { createRequestSupabase } from '@/lib/supabase/server';

export async function proxy(request: NextRequest) {
  const auth = createRequestSupabase(request);
  if (!auth.supabase) return NextResponse.next();

  // Refresh cookie transport here. The server loader verifies claims before using them.
  await auth.supabase.auth.getSession();
  return auth.applyCookies(NextResponse.next({ request }));
}

export const config = { matcher: ['/', '/backup', '/import'] };
