import 'server-only';
import { EncryptJWT, jwtDecrypt } from 'jose';
import type { PlatformRole, SessionTokens } from '@travelbuddy/domain-types';

/** Cookie names (docs/web/01 §6, ADR-0011). */
export const SESSION_COOKIE = 'tb_session';
export const CSRF_COOKIE = 'tb_csrf';
export const CSRF_HEADER = 'x-csrf-token';

/** Contents of the sealed session cookie. Never sent to browser JavaScript. */
export interface SessionData {
  at: string;
  /** Access token expiry, epoch ms. */
  atExp: number;
  rt: string;
  /** Refresh token expiry, epoch ms. */
  rtExp: number;
  uid: string;
  sid: string;
  roles: PlatformRole[];
}

const encoder = new TextEncoder();
const keyCache = new Map<string, Uint8Array>();

async function keyFor(secret: string): Promise<Uint8Array> {
  const cached = keyCache.get(secret);
  if (cached) return cached;
  // Derive a 256-bit key from the configured secret.
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(`tb-session-v1:${secret}`)));
  keyCache.set(secret, digest);
  return digest;
}

export function sessionFromTokens(tokens: SessionTokens, roles: PlatformRole[], userId: string): SessionData {
  return {
    at: tokens.access_token,
    atExp: Date.parse(tokens.access_token_expires_at),
    rt: tokens.refresh_token,
    rtExp: Date.parse(tokens.refresh_token_expires_at),
    uid: userId,
    sid: tokens.session_id,
    roles,
  };
}

/** JWE `dir` + `A256GCM`: confidential and tamper-evident. */
export async function sealSession(data: SessionData, secret: string): Promise<string> {
  return new EncryptJWT({ s: data })
    .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
    .setIssuedAt()
    .setExpirationTime(Math.floor(data.rtExp / 1000))
    .encrypt(await keyFor(secret));
}

export async function unsealSession(value: string | undefined, secret: string): Promise<SessionData | null> {
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, await keyFor(secret), { contentEncryptionAlgorithms: ['A256GCM'], keyManagementAlgorithms: ['dir'] });
    const s = payload.s as SessionData | undefined;
    if (!s || typeof s.at !== 'string' || typeof s.rt !== 'string' || typeof s.atExp !== 'number') return null;
    return s;
  } catch {
    return null;
  }
}

/** True when the access token is expired or will be within `skewMs`. */
export function needsRefresh(session: SessionData, now = Date.now(), skewMs = 60_000): boolean {
  return session.atExp - now < skewMs;
}

export function sessionCookieOptions(session: SessionData, secure: boolean) {
  return {
    httpOnly: true,
    secure,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: Math.max(0, Math.floor((session.rtExp - Date.now()) / 1000)),
  };
}

export function csrfCookieOptions(secure: boolean) {
  return { httpOnly: false, secure, sameSite: 'strict' as const, path: '/', maxAge: 60 * 60 * 24 * 30 };
}

export function newCsrfToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Buffer.from(bytes).toString('base64url');
}

/** Constant-time string comparison. */
export function safeEqual(a: string, b: string): boolean {
  const ab = encoder.encode(a);
  const bb = encoder.encode(b);
  let diff = ab.length ^ bb.length;
  for (let i = 0; i < Math.max(ab.length, bb.length); i++) diff |= (ab[i] ?? 0) ^ (bb[i] ?? 0);
  return diff === 0;
}
