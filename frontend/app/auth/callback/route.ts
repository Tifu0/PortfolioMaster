import { NextResponse, type NextRequest } from 'next/server';
import { getRequestOrigin } from '@/lib/supabase/request';
import { createRequestSupabase } from '@/lib/supabase/server';

export async function GET(request: NextRequest) {
  const auth = createRequestSupabase(request);
  const code = request.nextUrl.searchParams.get('code');
  const home = new URL('/', getRequestOrigin(request));
  if (!auth.supabase || !code) {
    home.searchParams.set('authError', 'confirmation');
  } else {
    const { error } = await auth.supabase.auth.exchangeCodeForSession(code);
    if (error) home.searchParams.set('authError', 'confirmation');
  }
  return auth.applyCookies(NextResponse.redirect(home));
}
