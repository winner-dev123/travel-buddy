import 'server-only';
import { createHmac, timingSafeEqual } from 'node:crypto';

/**
 * Verifies the platform's `X-TB-Signature: t=<unix s>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>`
 * header for the `webCacheRevalidation` webhook (contract `webhooks`, SAFE-012).
 *
 * - rejects timestamps more than `toleranceSeconds` away from now (replay protection);
 * - accepts any of up to two secrets (rotation);
 * - compares in constant time.
 */
export function verifyWebhookSignature(options: {
  header: string | null;
  rawBody: string;
  secrets: readonly string[];
  nowSeconds?: number;
  toleranceSeconds?: number;
}): boolean {
  const { header, rawBody, secrets } = options;
  if (!header || secrets.length === 0) return false;
  const parts = new Map<string, string[]>();
  for (const piece of header.split(',')) {
    const [key, ...rest] = piece.trim().split('=');
    if (!key || rest.length === 0) continue;
    parts.set(key, [...(parts.get(key) ?? []), rest.join('=')]);
  }
  const t = parts.get('t')?.[0];
  const signatures = parts.get('v1') ?? [];
  if (!t || !/^\d{1,12}$/.test(t) || signatures.length === 0) return false;
  const now = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  if (Math.abs(now - Number(t)) > (options.toleranceSeconds ?? 300)) return false;

  for (const secret of secrets) {
    const expected = createHmac('sha256', secret).update(`${t}.${rawBody}`).digest();
    for (const candidate of signatures) {
      if (!/^[0-9a-f]{64}$/i.test(candidate)) continue;
      const given = Buffer.from(candidate, 'hex');
      if (given.length === expected.length && timingSafeEqual(given, expected)) return true;
    }
  }
  return false;
}

/** Bounded, per-instance memory of processed event ids (delivery is at-least-once). */
export class RecentEvents {
  private readonly seen = new Map<string, number>();
  constructor(
    private readonly max = 5_000,
    private readonly ttlMs = 2 * 60 * 60 * 1000,
  ) {}

  /** Returns true the first time an id is seen within the TTL. */
  firstTime(id: string, now = Date.now()): boolean {
    for (const [key, at] of this.seen) {
      if (now - at <= this.ttlMs && this.seen.size <= this.max) break;
      this.seen.delete(key);
    }
    if (this.seen.has(id)) return false;
    this.seen.set(id, now);
    return true;
  }
}
