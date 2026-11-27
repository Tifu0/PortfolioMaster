import { NextResponse, type NextRequest } from 'next/server';
import { hasSameOrigin } from '@/lib/supabase/request';
import { createRequestSupabase } from '@/lib/supabase/server';

const forwardedRequestHeaders = ['accept', 'content-type', 'if-none-match', 'if-modified-since'];
const forwardedResponseHeaders = [
  'content-type', 'content-disposition', 'etag', 'last-modified', 'retry-after',
  'www-authenticate', 'x-accel-buffering', 'strict-transport-security', 'x-content-type-options',
  'x-frame-options',
];

function copyHeaders(source: Headers, keys: string[]): Headers {
  const result = new Headers();
  for (const key of keys) {
    const value = source.get(key);
    if (value !== null) result.set(key, value);
  }
  return result;
}

async function forward(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (path.some((segment) => segment === '.' || segment === '..' || /[/\\]/.test(segment))) {
    return NextResponse.json({ detail: 'Invalid API path.' }, { status: 400 });
  }

  const resource = path.join('/');
  const readOnly = request.method === 'GET' || request.method === 'HEAD';
  const modes = request.nextUrl.searchParams.getAll('mode');
  const triggersRefresh = resource === 'refresh/stream' && !(modes.length === 1 && modes[0] === 'listen');
  const site = request.headers.get('Sec-Fetch-Site');
  if ((!readOnly && !hasSameOrigin(request)) || (
    triggersRefresh && (request.headers.get('X-Portfolio-Mutation') !== '1' || (site && site !== 'same-origin'))
  )) {
    return NextResponse.json({ detail: 'Cross-origin request denied.' }, { status: 403 });
  }

  const backend = process.env.API_BASE_URL || process.env.BACKEND_URL
    || (process.env.NODE_ENV === 'production' ? null : 'http://localhost:8000');
  if (!backend) return NextResponse.json({ detail: 'Backend URL is not configured.' }, { status: 503 });

  const auth = createRequestSupabase(request);
  const headers = copyHeaders(request.headers, forwardedRequestHeaders);
  const isPublic = readOnly && ['config', 'health', 'healthcheck'].includes(resource);
  if (auth.supabase && !isPublic) {
    // The upstream verifies the token and authorizes every private operation.
    const { data: { session } } = await auth.supabase.auth.getSession();
    if (!session) return auth.applyCookies(NextResponse.json({ detail: 'Authentication required.' }, { status: 401 }));
    headers.set('Authorization', `Bearer ${session.access_token}`);
  }

  try {
    const upstreamUrl = new URL(backend);
    upstreamUrl.pathname = `${upstreamUrl.pathname.replace(/\/$/, '')}/api/${path.map(encodeURIComponent).join('/')}`;
    upstreamUrl.search = request.nextUrl.search;
    const init: RequestInit & { duplex?: 'half' } = {
      method: request.method,
      headers,
      cache: 'no-store',
      redirect: 'manual',
      signal: request.signal,
    };
    if (!readOnly && request.body) {
      init.body = request.body;
      init.duplex = 'half';
    }
    const upstream = await fetch(upstreamUrl, init);
    if (upstream.status >= 300 && upstream.status < 400 && upstream.status !== 304) {
      await upstream.body?.cancel();
      return auth.applyCookies(NextResponse.json({ detail: 'Unexpected backend redirect.' }, { status: 502 }));
    }
    return auth.applyCookies(new NextResponse(upstream.body, {
      status: upstream.status,
      headers: copyHeaders(upstream.headers, forwardedResponseHeaders),
    }));
  } catch {
    return auth.applyCookies(NextResponse.json({ detail: 'Backend unavailable.' }, { status: 502 }));
  }
}

export { forward as GET, forward as HEAD, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
