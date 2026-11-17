import { NextResponse, type NextRequest } from 'next/server';
import { getRequestOrigin, hasSameOrigin } from '@/lib/supabase/request';
import { createRequestSupabase } from '@/lib/supabase/server';

export async function POST(request: NextRequest) {
  if (!hasSameOrigin(request)) {
    return NextResponse.json({ error: 'Cross-origin request denied.' }, { status: 403 });
  }

  const auth = createRequestSupabase(request);
  const supabase = auth.supabase;
  if (!supabase) {
    return NextResponse.json({ error: 'Supabase authentication is not configured.' }, { status: 503 });
  }
  const respond = (body: object, status = 200) => auth.applyCookies(NextResponse.json(body, { status }));
  const credentials = await request.json().catch(() => null);

  if (credentials?.action === 'signOut') {
    const { error } = await supabase.auth.signOut();
    return error ? respond({ error: error.message }, 400) : respond({ user: null });
  }

  const { action, email, password } = credentials ?? {};
  if ((action !== 'signIn' && action !== 'signUp') || typeof email !== 'string' || typeof password !== 'string') {
    return respond({ error: 'Invalid authentication request.' }, 400);
  }

  const { data, error } = action === 'signIn'
    ? await supabase.auth.signInWithPassword({ email, password })
    : await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: new URL('/auth/callback', getRequestOrigin(request)).href },
    });

  if (error) return respond({ error: error.message }, action === 'signIn' ? 401 : 400);
  const user = data.session && data.user ? { id: data.user.id, email: data.user.email } : null;
  return respond({ user, needsConfirmation: action === 'signUp' && !user });
}
