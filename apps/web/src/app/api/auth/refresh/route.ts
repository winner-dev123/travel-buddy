import { NextResponse, type NextRequest } from 'next/server';
import { clearSessionCookies, readSession, refreshSession, requestIdFrom, writeSessionCookie } from '@/server/auth';
import { safeNextPath } from '@/server/safe-redirect';

export const dynamic = 'force-dynamic';

/**
 * Navigation-time refresh hop. Server Components redirect here when the access token is about to
 * expire because they cannot set cookies themselves. Refreshing only rotates the caller's own
 * tokens, so a cross-site trigger cannot do harm beyond a rotation.
 */
export async function GET(request: NextRequest) {
  const next = safeNextPath(request.nextUrl.searchParams.get('next'));
  const session = await readSession(request);
  if (!session) {
    return NextResponse.redirect(new URL(`/login?next=${encodeURIComponent(next)}`, request.url), 303);
  }
  const refreshed = await refreshSession(session, requestIdFrom(request));
  if (!refreshed) {
    const response = NextResponse.redirect(new URL(`/login?next=${encodeURIComponent(next)}&reason=expired`, request.url), 303);
    clearSessionCookies(response);
    return response;
  }
  const response = NextResponse.redirect(new URL(next, request.url), 303);
  await writeSessionCookie(response, refreshed);
  response.headers.set('cache-control', 'no-store');
  return response;
}
