import { NextResponse, type NextRequest } from 'next/server';
import { clearSessionCookies, readSession, verifyCsrf } from '@/server/auth';
import { serverApi } from '@/server/platform';

export const dynamic = 'force-dynamic';

/** Revokes the platform session and clears cookies. CSRF-protected. */
export async function POST(request: NextRequest) {
  if (!verifyCsrf(request)) {
    return NextResponse.json({ code: 'csrf_failed', title: 'CSRF check failed', status: 403 }, { status: 403 });
  }
  const session = await readSession(request);
  if (session) {
    // Contract: Bearer-authenticated, revokes the current session. Best effort — cookies are
    // cleared regardless so the browser is signed out even if the platform is unreachable.
    const api = await serverApi({ accessToken: session.at });
    await api.auth.logout({}).catch(() => undefined);
  }
  const response = NextResponse.json({ redirect: '/' });
  clearSessionCookies(response);
  response.headers.set('cache-control', 'no-store');
  return response;
}

/**
 * Local cleanup only, used when the platform has already rejected the session
 * (`?reason=expired`). It does not call the platform, so it cannot be abused to revoke sessions.
 */
export async function GET(request: NextRequest) {
  const response = NextResponse.redirect(new URL('/login?reason=expired', request.url), 303);
  clearSessionCookies(response);
  return response;
}
