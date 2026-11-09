import { revalidateTag } from 'next/cache';
import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { env } from '@/server/env';
import { RecentEvents, verifyWebhookSignature } from '@/server/webhook-signature';

export const dynamic = 'force-dynamic';

/**
 * On-demand ISR invalidation called by the platform outbox (contract `webhooks: webCacheRevalidation`,
 * SAFE-012). Disabled (404) unless WEB_REVALIDATE_SECRETS is configured.
 */
const PRIVACY_REASONS = new Set([
  'post_removed',
  'post_deleted',
  'post_visibility_changed',
  'profile_visibility_changed',
  'indexing_consent_changed',
]);

const TAG = /^(story:[0-9a-f-]{36}|stories|profile:[a-z0-9_.]{3,30}|destination:[a-z0-9-]{1,120}|guide:[0-9a-f-]{36}|sitemap)$/;

const bodySchema = z.object({
  event_id: z.string().min(1).max(100),
  occurred_at: z.string(),
  reason: z.enum([
    'post_removed',
    'post_deleted',
    'post_visibility_changed',
    'post_published',
    'profile_visibility_changed',
    'indexing_consent_changed',
    'destination_changed',
    'guide_changed',
  ]),
  tags: z.array(z.string()).max(50),
});

const recent = new RecentEvents();

export async function POST(request: NextRequest) {
  const secrets = env().revalidateSecrets;
  if (secrets.length === 0) return new NextResponse(null, { status: 404 });

  const rawBody = await request.text();
  if (rawBody.length > 64_000) return new NextResponse(null, { status: 413 });
  if (!verifyWebhookSignature({ header: request.headers.get('x-tb-signature'), rawBody, secrets })) {
    // 401 is final for the sender (not retried): a bad signature never becomes valid.
    return NextResponse.json({ code: 'unauthenticated', status: 401 }, { status: 401 });
  }

  let payload: z.infer<typeof bodySchema>;
  try {
    payload = bodySchema.parse(JSON.parse(rawBody));
  } catch {
    return NextResponse.json({ code: 'validation_failed', status: 400 }, { status: 400 });
  }

  if (recent.firstTime(payload.event_id)) {
    // Privacy-relevant changes must never serve stale content; ordinary updates may (stale-while-revalidate).
    const profile = PRIVACY_REASONS.has(payload.reason) ? { expire: 0 } : 'max';
    const tags = new Set(payload.tags.filter((tag) => TAG.test(tag)));
    // Catalog fetches are tagged `destinations` (a destination's slug isn't known before fetching it by path,
    // and guide lists hang off the destination), so destination and guide changes purge the catalog too.
    if ([...tags].some((tag) => tag.startsWith('destination:') || tag.startsWith('guide:'))) tags.add('destinations');
    for (const tag of tags) revalidateTag(tag, profile);
  }
  return new NextResponse(null, { status: 204 });
}
