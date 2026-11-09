import { createHmac } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { RecentEvents, verifyWebhookSignature } from './webhook-signature';

const SECRET = 'whsec_current_0123456789abcdef0123456789abcdef';
const OLD = 'whsec_previous_0123456789abcdef0123456789abcdef';
const body = JSON.stringify({ event_id: 'e1', occurred_at: '2026-11-09T10:00:00Z', reason: 'post_removed', tags: ['stories'] });
const sign = (secret: string, t: number, raw = body) => `t=${t},v1=${createHmac('sha256', secret).update(`${t}.${raw}`).digest('hex')}`;
const now = 1_794_200_000;

describe('verifyWebhookSignature (SAFE-012)', () => {
  it('accepts a valid signature from either rotation secret', () => {
    expect(verifyWebhookSignature({ header: sign(SECRET, now), rawBody: body, secrets: [SECRET, OLD], nowSeconds: now })).toBe(true);
    expect(verifyWebhookSignature({ header: sign(OLD, now), rawBody: body, secrets: [SECRET, OLD], nowSeconds: now })).toBe(true);
  });

  it('rejects tampered bodies, unknown secrets and missing headers', () => {
    expect(verifyWebhookSignature({ header: sign(SECRET, now), rawBody: `${body} `, secrets: [SECRET], nowSeconds: now })).toBe(false);
    expect(verifyWebhookSignature({ header: sign('other-secret', now), rawBody: body, secrets: [SECRET], nowSeconds: now })).toBe(false);
    expect(verifyWebhookSignature({ header: null, rawBody: body, secrets: [SECRET], nowSeconds: now })).toBe(false);
    expect(verifyWebhookSignature({ header: 'garbage', rawBody: body, secrets: [SECRET], nowSeconds: now })).toBe(false);
  });

  it('rejects timestamps outside the 300 s window (replay)', () => {
    expect(verifyWebhookSignature({ header: sign(SECRET, now - 301), rawBody: body, secrets: [SECRET], nowSeconds: now })).toBe(false);
    expect(verifyWebhookSignature({ header: sign(SECRET, now + 299), rawBody: body, secrets: [SECRET], nowSeconds: now })).toBe(true);
  });

  it('never verifies when no secret is configured', () => {
    expect(verifyWebhookSignature({ header: sign(SECRET, now), rawBody: body, secrets: [], nowSeconds: now })).toBe(false);
  });
});

describe('RecentEvents (at-least-once delivery)', () => {
  it('processes an event id once within the TTL', () => {
    const recent = new RecentEvents(10, 1_000);
    expect(recent.firstTime('a', 0)).toBe(true);
    expect(recent.firstTime('a', 500)).toBe(false);
    expect(recent.firstTime('a', 2_000)).toBe(true);
  });
});
