// @vitest-environment node
import { createHmac } from 'node:crypto';
import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const SECRET = 'r'.repeat(40);
const revalidateTag = vi.fn();
vi.mock('next/cache', () => ({ revalidateTag: (...args: unknown[]) => revalidateTag(...args) }));
vi.mock('@/server/env', () => ({ env: () => ({ revalidateSecrets: [SECRET] }) }));

const { POST } = await import('./route');

let seq = 0;
function signed(body: object, secret = SECRET) {
  const raw = JSON.stringify(body);
  const t = Math.floor(Date.now() / 1000);
  const v1 = createHmac('sha256', secret).update(`${t}.${raw}`).digest('hex');
  return new NextRequest('http://localhost/api/revalidate', { method: 'POST', body: raw, headers: { 'x-tb-signature': `t=${t},v1=${v1}` } });
}
const event = (reason: string, tags: string[]) => ({ event_id: `evt-${++seq}`, occurred_at: new Date().toISOString(), reason, tags });
const purged = () => revalidateTag.mock.calls.map(([tag, profile]) => [tag, profile]);

describe('POST /api/revalidate', () => {
  beforeEach(() => revalidateTag.mockReset());

  it('purges privacy changes immediately, including the author stories and sitemap', async () => {
    const res = await POST(signed(event('profile_visibility_changed', ['profile:ana.silva', 'profile:ana_old', 'stories', 'sitemap'])));
    expect(res.status).toBe(204);
    expect(purged()).toEqual([
      ['profile:ana.silva', { expire: 0 }],
      ['profile:ana_old', { expire: 0 }],
      ['stories', { expire: 0 }],
      ['sitemap', { expire: 0 }],
    ]);
  });

  it('maps destination and guide tags to the catalog tag (slugs are unknown at fetch time)', async () => {
    await POST(signed(event('destination_changed', ['destination:rio-de-janeiro-br', 'sitemap'])));
    expect(purged()).toEqual([
      ['destination:rio-de-janeiro-br', 'max'],
      ['sitemap', 'max'],
      ['destinations', 'max'],
    ]);
    revalidateTag.mockReset();
    await POST(signed(event('guide_changed', ['guide:0193f1c2-0000-7000-8000-000000000001'])));
    expect(purged().map(([tag]) => tag)).toEqual(['guide:0193f1c2-0000-7000-8000-000000000001', 'destinations']);
  });

  it('ignores tags outside the grammar and never lets a sender name the catalog tag directly', async () => {
    await POST(signed(event('post_published', ['destinations', 'client-config', 'profile:UPPER', 'stories'])));
    expect(purged().map(([tag]) => tag)).toEqual(['stories']);
  });

  it('is idempotent on event_id', async () => {
    const body = event('post_deleted', ['story:0193f1c2-0000-7000-8000-000000000002']);
    await POST(signed(body));
    await POST(signed(body));
    expect(revalidateTag).toHaveBeenCalledTimes(1);
  });

  it('rejects a bad signature (401, final for the sender) and an unknown reason (400)', async () => {
    expect((await POST(signed(event('post_deleted', ['stories']), 'x'.repeat(40)))).status).toBe(401);
    expect((await POST(signed(event('something_else', ['stories'])))).status).toBe(400);
    expect(revalidateTag).not.toHaveBeenCalled();
  });
});
