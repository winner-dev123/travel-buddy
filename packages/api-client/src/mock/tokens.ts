import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

/**
 * Self-describing, HMAC-signed MOCK tokens. Serverless hosts (e.g. a Vercel demo) run several
 * isolated instances with separate memory, so a session created in one instance must be
 * verifiable in another. Real platform tokens are issued by the backend (doc 02 §8); this exists
 * only so the development/demo mock adapter behaves consistently.
 */
export interface MockTokenClaims {
  /** kind: access or refresh */
  k: 'a' | 'r';
  /** user id */
  u: string;
  /** session id */
  s: string;
  /** expiry, epoch ms */
  e: number;
  /** minimal identity so a registered (non-seeded) user can be rebuilt in another instance */
  id?: { h: string; n: string; m: string; l: string };
  /** nonce */
  x: string;
}

const b64url = (buf: Buffer) => buf.toString('base64url');

export function signMockToken(claims: Omit<MockTokenClaims, 'x'>, secret: string): string {
  const body = b64url(Buffer.from(JSON.stringify({ ...claims, x: b64url(randomBytes(9)) })));
  const sig = b64url(createHmac('sha256', secret).update(body).digest());
  return `${claims.k === 'a' ? 'mat' : 'mrt'}.${body}.${sig}`;
}

/** Returns the claims when the signature is valid (expiry is checked by the caller). */
export function verifyMockToken(token: string | undefined, secret: string): MockTokenClaims | null {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  const [, body, sig] = parts as [string, string, string];
  const expected = createHmac('sha256', secret).update(body).digest();
  const given = Buffer.from(sig, 'base64url');
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return null;
  try {
    const claims = JSON.parse(Buffer.from(body, 'base64url').toString('utf8')) as MockTokenClaims;
    return typeof claims.u === 'string' && typeof claims.s === 'string' && typeof claims.e === 'number' ? claims : null;
  } catch {
    return null;
  }
}
