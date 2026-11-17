import type { NextRequest } from 'next/server';

export function getRequestOrigin(request: NextRequest): string {
  const host = request.headers.get('Host');
  // Next normalizes loopback IPs to localhost in NextURL.
  if (request.nextUrl.hostname === 'localhost' && host && /^(127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host)) {
    return `${request.nextUrl.protocol}//${host}`;
  }
  return request.nextUrl.origin;
}

export function hasSameOrigin(request: NextRequest): boolean {
  const site = request.headers.get('Sec-Fetch-Site');
  return (!site || site === 'same-origin') && request.headers.get('Origin') === getRequestOrigin(request);
}
