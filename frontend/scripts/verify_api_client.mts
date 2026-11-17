import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { NextRequest, type NextResponse } from 'next/server';
import * as api from '../lib/api';

console.log('Testing Phase 2 API Client exports...');

const expectedFunctions = [
  'getPositions',
  'getInstruments',
  'getInstrument',
  'createInstrument',
  'updateInstrument',
  'deleteInstrument',
  'refreshInstrument',
  'refreshAll',
  'previewImport',
  'confirmImport',
  'wipeDatabase',
];

let failed = false;
for (const fnName of expectedFunctions) {
  if (typeof (api as Record<string, unknown>)[fnName] !== 'function') {
    console.error(`❌ Missing expected function: ${fnName}`);
    failed = true;
  } else {
    console.log(`✅ ${fnName} is exported and typed`);
  }
}

if (failed) {
  process.exit(1);
} else {
  console.log('All 11 API client functions verified successfully!');
}

const originalFetch = globalThis.fetch;
const serverToken = 'fixture-server-token';
const authorizationHeaders: Array<string | null> = [];
globalThis.fetch = async (_input, init) => {
  authorizationHeaders.push(new Headers(init?.headers).get('Authorization'));
  return Response.json({ positions: [] }, { headers: { ETag: 'fixture-etag' } });
};

try {
  await Promise.all([
    api.getPositions('no-store', serverToken),
    api.getMetrics('no-store', serverToken),
    api.getPositions('no-store', 'other-server-token'),
  ]);
  assert.deepEqual(authorizationHeaders, [
    'Bearer fixture-server-token', 'Bearer fixture-server-token', 'Bearer other-server-token',
  ]);
  globalThis.fetch = async () => new Response(null, { status: 304 });
  await assert.rejects(api.getPositions('no-store', 'other-server-token'), api.ApiError);
} finally {
  globalThis.fetch = originalFetch;
}

process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://auth.example';
process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = 'fixture-publishable-key';
process.env.API_BASE_URL = 'https://backend.example';

const { GET, POST } = await import('../app/api/[...path]/route');
const authRoute = await import('../app/api/auth/route');
const callbackRoute = await import('../app/auth/callback/route');
const streamRoute = { params: Promise.resolve({ path: ['refresh', 'stream'] }) };
const positionsRoute = { params: Promise.resolve({ path: ['positions'] }) };
const origin = 'https://portfolio.example';
const { getRequestOrigin } = await import('../lib/supabase/request');
assert.equal(getRequestOrigin(new NextRequest('http://localhost:4918/api/auth', {
  headers: { Host: '127.0.0.1:4918' },
})), 'http://127.0.0.1:4918');
const user = {
  id: '72c338c2-f1ac-4e90-8e1e-ad2a1e38c896',
  email: 'fixture@example.com',
  aud: 'authenticated',
  role: 'authenticated',
  app_metadata: {},
  user_metadata: {},
  created_at: '2026-11-01T00:00:00Z',
};
const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url');
const jwtPayload = `${encode({ typ: 'JWT', alg: 'HS256' })}.${encode({
  sub: user.id, email: user.email, exp: Math.floor(Date.now() / 1000) + 3600,
})}`;
const accessToken = `${jwtPayload}.${createHmac('sha256', 'test-fixture').update(jwtPayload).digest('base64url')}`;
const tokenResponse = { access_token: accessToken, refresh_token: 'fixture-refresh', expires_in: 3600, token_type: 'bearer', user };
let upstreamRequest: Request | undefined;
globalThis.fetch = async (input, init) => {
  const request = new Request(input, init);
  const url = new URL(request.url);
  if (url.origin === 'https://auth.example') {
    if (url.pathname === '/auth/v1/token') return Response.json(tokenResponse);
    if (url.pathname === '/auth/v1/signup') return Response.json(user);
    if (url.pathname === '/auth/v1/logout') return new Response(null, { status: 204 });
    throw new Error(`Unexpected fixture auth path: ${url.pathname}`);
  }
  assert.equal(url.origin, 'https://backend.example');
  upstreamRequest = request;
  return new Response(null, { status: 304, headers: { ETag: 'same-etag', 'Set-Cookie': 'upstream=private' } });
};

function authRequest(action: 'signIn' | 'signUp' | 'signOut', cookie?: string) {
  const headers = new Headers({ Origin: origin, 'Content-Type': 'application/json' });
  if (cookie) headers.set('Cookie', cookie);
  return new NextRequest(`${origin}/api/auth`, {
    method: 'POST', headers, body: JSON.stringify({ action, email: user.email, password: 'fixture-password' }),
  });
}

function sessionCookie(response: Pick<NextResponse, 'cookies'>): string {
  const cookies = response.cookies.getAll();
  assert.ok(cookies.length > 0);
  for (const cookie of cookies) {
    assert.equal(cookie.httpOnly, true);
    assert.equal(cookie.secure, true);
    assert.equal(cookie.sameSite, 'lax');
  }
  return cookies.map(({ name, value }) => `${name}=${value}`).join('; ');
}

try {
  const ambiguousTrigger = await GET(new NextRequest('https://portfolio.example/api/refresh/stream?mode=listen&mode=start', {
    headers: { 'Sec-Fetch-Site': 'cross-site' },
  }), streamRoute);
  assert.equal(ambiguousTrigger.status, 403, 'An ambiguous mode must not bypass the refresh trigger origin guard.');
  const crossOriginMutation = await POST(new NextRequest(`${origin}/api/positions`, {
    method: 'POST', headers: { Origin: 'https://untrusted.example' },
  }), positionsRoute);
  assert.equal(crossOriginMutation.status, 403);

  const login = await authRoute.POST(authRequest('signIn'));
  assert.equal(login.status, 200);
  assert.deepEqual(await login.json(), { user: { id: user.id, email: user.email }, needsConfirmation: false });
  assert.equal(login.headers.get('Cache-Control'), 'private, no-store');
  const cookie = sessionCookie(login);

  const proxied = await GET(new NextRequest(`${origin}/api/positions`, {
    headers: { Cookie: cookie, Authorization: 'Bearer untrusted', 'If-None-Match': 'same-etag' },
  }), positionsRoute);
  assert.equal(proxied.status, 304);
  assert.equal(proxied.headers.get('ETag'), 'same-etag');
  assert.equal(proxied.headers.get('Set-Cookie'), null);
  assert.equal(proxied.headers.get('Cache-Control'), 'private, no-store');
  assert.ok(upstreamRequest);
  assert.equal(upstreamRequest.headers.get('If-None-Match'), 'same-etag');
  assert.equal(upstreamRequest.headers.get('Authorization'), `Bearer ${accessToken}`);
  assert.equal(upstreamRequest.headers.get('Cookie'), null);

  const signup = await authRoute.POST(authRequest('signUp'));
  assert.deepEqual(await signup.json(), { user: null, needsConfirmation: true });
  const verifier = sessionCookie(signup);
  const callback = await callbackRoute.GET(new NextRequest(`${origin}/auth/callback?code=fixture-code`, {
    headers: { Cookie: verifier },
  }));
  assert.equal(callback.headers.get('Location'), `${origin}/`);
  sessionCookie(callback);

  const logout = await authRoute.POST(authRequest('signOut', cookie));
  assert.equal(logout.status, 200);
  assert.ok(logout.cookies.getAll().some(({ maxAge }) => maxAge === 0));
} finally {
  globalThis.fetch = originalFetch;
}
