import 'server-only';
import type { NextRequest, NextResponse } from 'next/server';
import { isApiError } from '@travelbuddy/api-client';
import type { AuthResult } from '@travelbuddy/domain-types';
import { env } from './env';
import { serverApi } from './platform';
import {
  CSRF_COOKIE,
  CSRF_HEADER,
  csrfCookieOptions,
  newCsrfToken,
  safeEqual,
  sealSession,
  SESSION_COOKIE,
  sessionCookieOptions,
  sessionFromTokens,
  unsealSession,
  type SessionData,
} from './session';

export async function readSession(request: NextRequest): Promise<SessionData | null> {
  return unsealSession(request.cookies.get(SESSION_COOKIE)?.value, env().sessionSecret);
}

/** Writes a brand-new session cookie and rotates the CSRF token (prevents session fixation). */
export async function writeLoginCookies(response: NextResponse, result: AuthResult): Promise<void> {
  const session = sessionFromTokens(result.tokens, result.user.roles, result.user.account.id);
  await writeSessionCookie(response, session);
  response.cookies.set(CSRF_COOKIE, newCsrfToken(), csrfCookieOptions(env().secureCookies));
}

export async function writeSessionCookie(response: NextResponse, session: SessionData): Promise<void> {
  const e = env();
  response.cookies.set(SESSION_COOKIE, await sealSession(session, e.sessionSecret), sessionCookieOptions(session, e.secureCookies));
}

export function clearSessionCookies(response: NextResponse): void {
  response.cookies.set(SESSION_COOKIE, '', { httpOnly: true, secure: env().secureCookies, sameSite: 'lax', path: '/', maxAge: 0 });
}

/**
 * Exchanges the refresh token for a new pair. Returns null when the platform rejects it
 * (expired, revoked or reused outside the leeway), in which case the caller signs the user out.
 */
export async function refreshSession(session: SessionData, requestId?: string): Promise<SessionData | null> {
  const api = await serverApi({ requestId });
  try {
    const tokens = await api.auth.refresh({ refresh_token: session.rt });
    return sessionFromTokens(tokens, session.roles, session.uid);
  } catch (error) {
    if (isApiError(error) && error.status >= 400 && error.status < 500) return null;
    throw error;
  }
}

/**
 * CSRF check for state-changing BFF requests (ADR-0011): double-submit token + same-origin.
 */
export function verifyCsrf(request: NextRequest): boolean {
  const site = request.headers.get('sec-fetch-site');
  if (site && site !== 'same-origin' && site !== 'none') return false;
  const origin = request.headers.get('origin');
  if (origin) {
    const expected = new URL(env().siteUrl).origin;
    const own = request.nextUrl.origin;
    if (origin !== expected && origin !== own) return false;
  }
  const header = request.headers.get(CSRF_HEADER);
  const cookie = request.cookies.get(CSRF_COOKIE)?.value;
  return Boolean(header && cookie && safeEqual(header, cookie));
}

export function requestIdFrom(request: NextRequest): string {
  const incoming = request.headers.get('x-request-id');
  return incoming && /^[A-Za-z0-9-]{8,64}$/.test(incoming) ? incoming : crypto.randomUUID();
}
