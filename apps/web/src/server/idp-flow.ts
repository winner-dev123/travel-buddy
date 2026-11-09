import 'server-only';
import { EncryptJWT, jwtDecrypt } from 'jose';

/**
 * Short-lived, sealed (JWE dir/A256GCM) cookies for identity-provider flows (ADR-0011, ADR-0020).
 *
 *  - `tb_idp_flow`: the PKCE code verifier plus where to go afterwards. It binds the IdP's return
 *    (OAuth, email confirmation or password-recovery link) to the browser that started the flow,
 *    so a code injected from elsewhere cannot be exchanged (login-CSRF protection).
 *  - `tb_idp_pending`: a Supabase access token kept for one follow-up step (finishing registration
 *    or choosing a new password). HttpOnly, sealed, at most 15 minutes.
 */

export const FLOW_COOKIE = 'tb_idp_flow';
export const PENDING_COOKIE = 'tb_idp_pending';
export const FLOW_TTL_SECONDS = 60 * 60;
export const PENDING_TTL_SECONDS = 15 * 60;

export type FlowIntent = 'login' | 'signup' | 'reset';

export interface IdpFlow {
  /** PKCE code verifier. */
  v: string;
  intent: FlowIntent;
  next: string;
  locale: string;
  /** Collected by the signup form so a confirmed email can register without another step. */
  reg?: { birth_date: string; terms: string; privacy: string };
}

export interface PendingIdp {
  /** Supabase access token. */
  t: string;
  /** Token expiry, epoch ms. */
  e: number;
  kind: 'register' | 'reset';
  next: string;
  locale: string;
}

type Kind = 'flow' | 'pending';

const encoder = new TextEncoder();

async function keyFor(secret: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(`tb-idp-v1:${secret}`)));
}

export function newCodeVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Buffer.from(bytes).toString('base64url');
}

/** RFC 7636 S256: BASE64URL(SHA256(ASCII(code_verifier))). */
export async function codeChallengeS256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', encoder.encode(verifier));
  return Buffer.from(new Uint8Array(digest)).toString('base64url');
}

export async function sealIdp(kind: 'flow', value: IdpFlow, secret: string, ttlSeconds: number): Promise<string>;
export async function sealIdp(kind: 'pending', value: PendingIdp, secret: string, ttlSeconds: number): Promise<string>;
export async function sealIdp(kind: Kind, value: IdpFlow | PendingIdp, secret: string, ttlSeconds: number): Promise<string> {
  return new EncryptJWT({ k: kind, d: value })
    .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
    .setIssuedAt()
    .setExpirationTime(Math.floor(Date.now() / 1000) + Math.max(1, Math.floor(ttlSeconds)))
    .encrypt(await keyFor(secret));
}

export async function unsealIdp(kind: 'flow', raw: string | undefined, secret: string): Promise<IdpFlow | null>;
export async function unsealIdp(kind: 'pending', raw: string | undefined, secret: string): Promise<PendingIdp | null>;
export async function unsealIdp(kind: Kind, raw: string | undefined, secret: string): Promise<IdpFlow | PendingIdp | null> {
  if (!raw) return null;
  try {
    const { payload } = await jwtDecrypt(raw, await keyFor(secret), { contentEncryptionAlgorithms: ['A256GCM'], keyManagementAlgorithms: ['dir'] });
    if (payload.k !== kind || typeof payload.d !== 'object' || payload.d === null) return null;
    const d = payload.d as Record<string, unknown>;
    if (kind === 'flow' && typeof d.v !== 'string') return null;
    if (kind === 'pending' && typeof d.t !== 'string') return null;
    return d as unknown as IdpFlow | PendingIdp;
  } catch {
    return null;
  }
}

/** SameSite=Lax: the cookie must accompany the top-level GET back from the IdP. */
export function idpCookieOptions(secure: boolean, maxAgeSeconds: number, path: string) {
  return { httpOnly: true, secure, sameSite: 'lax' as const, path, maxAge: Math.max(0, Math.floor(maxAgeSeconds)) };
}

/** Flow cookies are read only by the callback; pending cookies also by the follow-up pages. */
export const FLOW_COOKIE_PATH = '/api/auth';
export const PENDING_COOKIE_PATH = '/';
