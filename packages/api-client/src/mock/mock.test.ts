import { beforeEach, describe, expect, it } from 'vitest';
import { ApiClient } from '../core/client';
import { ApiError } from '../core/errors';
import { createApi, type Api } from '../endpoints';
import { createMockPlatform, listDevPersonas, type MockPlatform } from './index';

let clock = Date.UTC(2026, 10, 9, 12, 0, 0);
const now = () => clock;

function clientFor(platform: MockPlatform, token?: string, locale = 'en'): Api {
  return createApi(
    new ApiClient(platform.transport, {
      headers: () => ({ 'Accept-Language': locale, ...(token ? { Authorization: `Bearer ${token}` } : {}) }),
    }),
  );
}

async function signIn(platform: MockPlatform, handle: string) {
  const anon = clientFor(platform);
  const persona = listDevPersonas().find((p) => p.handle === handle)!;
  const { id_token } = await anon.auth.devIdpToken({ sub: persona.sub, email: persona.email });
  const result = await anon.auth.login({ id_token, client: 'web' });
  return { result, api: clientFor(platform, result.tokens.access_token) };
}

async function expectApiError(promise: Promise<unknown>, status: number, code: string) {
  const error = await promise.then(() => null, (e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).status).toBe(status);
  expect((error as ApiError).code).toBe(code);
}

const REGISTER = { client: 'web' as const, accepted_terms_version: '2026-11', accepted_privacy_version: '2026-11' };

describe('mock platform — identity', () => {
  let platform: MockPlatform;
  beforeEach(() => {
    clock = Date.UTC(2026, 10, 9, 12, 0, 0);
    platform = createMockPlatform({ now });
  });

  it('signs in a persona through the dev IdP and returns the contract Me aggregate', async () => {
    const { result } = await signIn(platform, 'amelia');
    expect(result.user.profile.handle).toBe('amelia');
    expect(result.user.entitlements.plan).toBe('free');
    expect(result.user.entitlements.features['groups.create']).toBe(false);
    expect(result.user.browse_destination?.path).toBe('brazil/rio-de-janeiro');
    expect(result.user.privacy.discovery_enabled).toBe(false);
  });

  it('registers a new adult with onboarding pending and privacy-preserving defaults; rejects minors', async () => {
    const anon = clientFor(platform);
    const { id_token } = await anon.auth.devIdpToken({ sub: 'new:1', email: 'new.person@example.test', name: 'New Person' });
    await expectApiError(anon.auth.register({ ...REGISTER, id_token, birth_date: '2012-01-01', locale: 'en' }), 403, 'age_restricted');
    const result = await anon.auth.register({ ...REGISTER, id_token, birth_date: '1995-06-01', locale: 'pt-BR' });
    expect(result.is_new_user).toBe(true);
    expect(result.user.onboarding_completed).toBe(false);
    expect(result.user.preferences.ui_locale).toBe('pt-BR');
    expect(result.user.privacy.discovery_enabled).toBe(false);
    expect(result.user.privacy.location_consent).toBeNull();
  });

  it('rejects missing tokens and expires access tokens after 15 minutes', async () => {
    await expectApiError(clientFor(platform).me.get(), 401, 'unauthenticated');
    const { api } = await signIn(platform, 'amelia');
    clock += 16 * 60 * 1000;
    await expectApiError(api.me.get(), 401, 'token_expired');
  });

  it('rotates refresh tokens with a 30 s reuse leeway, then revokes the family on late reuse', async () => {
    const { result } = await signIn(platform, 'amelia');
    const anon = clientFor(platform);
    const first = await anon.auth.refresh({ refresh_token: result.tokens.refresh_token });
    const parallel = await anon.auth.refresh({ refresh_token: result.tokens.refresh_token });
    expect(parallel.refresh_token).toBe(first.refresh_token);
    clock += 31_000;
    await expectApiError(anon.auth.refresh({ refresh_token: result.tokens.refresh_token }), 401, 'refresh_token_reused');
    await expectApiError(anon.auth.refresh({ refresh_token: first.refresh_token }), 401, 'unauthenticated');
  });

  it('logout revokes the session', async () => {
    const { api } = await signIn(platform, 'yuki');
    await api.auth.logout();
    await expectApiError(api.me.get(), 401, 'session_revoked');
  });
});

describe('mock platform — destinations and guides', () => {
  let platform: MockPlatform;
  beforeEach(() => {
    platform = createMockPlatform({ now });
  });

  it('localizes names via Accept-Language and exposes directory card fields', async () => {
    const pt = clientFor(platform, undefined, 'pt-BR,pt;q=0.9');
    const tokyo = await pt.destinations.lookup('japan/tokyo');
    expect(tokyo.name).toBe('Tóquio');
    expect(tokyo.country_name).toBe('Japão');
    expect(tokyo.continent).toBe('asia');
    expect(tokyo.ancestors.map((a) => a.slug)).toEqual(['japan']);
    expect(tokyo.has_guides).toBe(true);
  });

  it('lists destinations anonymously with filters and a stable slug order for sitemaps', async () => {
    const anon = clientFor(platform);
    const cities = await anon.destinations.list({ kind: ['city'], continent: 'europe', sort: 'slug', limit: 100 });
    expect(cities.data.length).toBeGreaterThan(3);
    expect(cities.data.every((d) => d.kind === 'city' && d.continent === 'europe')).toBe(true);
    const paths = cities.data.map((d) => d.path);
    expect([...paths].sort()).toEqual(paths);
  });

  it('serves free guides anonymously, including structured FAQ sections', async () => {
    const anon = clientFor(platform);
    const rio = await anon.destinations.lookup('brazil/rio-de-janeiro');
    const { data } = await anon.destinations.guides(rio.id);
    const guide = await anon.guides.get(data[0]!.id);
    const faq = guide.sections.find((s) => s.kind === 'faq');
    expect(faq?.faq_items?.length).toBeGreaterThan(0);
    expect(faq?.faq_items?.[0]).toHaveProperty('answer_markdown');
  });
});

describe('mock platform — social and privacy', () => {
  let platform: MockPlatform;
  beforeEach(() => {
    clock = Date.UTC(2026, 10, 9, 12, 0, 0);
    platform = createMockPlatform({ now });
  });

  it('public stories expose only public posts and carry no viewer state', async () => {
    const page = await clientFor(platform).publicPosts.list({ limit: 100 });
    const bodies = page.data.map((p) => p.body);
    expect(bodies.some((c) => c.includes('reef-safe sunscreen'))).toBe(false);
    expect(bodies.some((c) => c.includes('Ilha Grande'))).toBe(false);
    expect(page.data.every((p) => p.visibility === 'public' && !('viewer' in p))).toBe(true);
  });

  it('hides non-visible posts with 404 rather than 403', async () => {
    const { api: amelia } = await signIn(platform, 'amelia');
    const { api: yuki } = await signIn(platform, 'yuki');
    const feed = await amelia.feed.get({ tab: 'for_you', limit: 50 });
    const privateNote = feed.data.find((p) => p.body.includes('reef-safe'));
    expect(privateNote?.viewer.is_author).toBe(true);
    await expectApiError(yuki.posts.get(privateNote!.id), 404, 'not_found');
  });

  it('prioritizes the selected destination and explains why', async () => {
    const { api } = await signIn(platform, 'amelia');
    const rio = await api.feed.get({ tab: 'for_you' });
    expect(rio.context.source).toBe('selected');
    expect(rio.context.destination?.path).toBe('brazil/rio-de-janeiro');
    expect(rio.data.every((p) => p.primary_destination?.path.startsWith('brazil/rio-de-janeiro'))).toBe(true);
    const tokyoId = (await api.destinations.lookup('japan/tokyo')).id;
    const tokyo = await api.feed.get({ tab: 'for_you', destination_id: tokyoId });
    expect(tokyo.context.destination?.name).toBe('Tokyo');
    expect(tokyo.data.length).toBeGreaterThan(0);
    expect(tokyo.data.every((p) => p.primary_destination?.path.startsWith('japan/tokyo'))).toBe(true);
  });

  it('uses the rounded device location for Nearby and never echoes coordinates', async () => {
    const { api } = await signIn(platform, 'amelia');
    const nearby = await api.feed.get({ tab: 'nearby', near: '-22.971,-43.182', radius_km: 5 });
    expect(nearby.context.source).toBe('gps');
    expect(nearby.context.destination?.slug).toBe('rio-de-janeiro');
    expect(JSON.stringify(nearby)).not.toContain('-22.971');
    await expectApiError(api.feed.get({ tab: 'nearby' }), 422, 'validation_failed');
  });

  it('paginates with opaque cursors bound to the query', async () => {
    const { api } = await signIn(platform, 'noah');
    const first = await api.feed.get({ tab: 'for_you', limit: 5 });
    expect(first.page.has_more).toBe(true);
    const second = await api.feed.get({ tab: 'for_you', limit: 5, cursor: first.page.next_cursor });
    expect(second.data[0]?.id).not.toBe(first.data[0]?.id);
    await expectApiError(api.feed.get({ tab: 'following', cursor: first.page.next_cursor }), 422, 'validation_failed');
  });

  it('upserts one reaction per user and blocks hide content both ways', async () => {
    const { api: amelia } = await signIn(platform, 'amelia');
    const { api: lucas, result: lucasAuth } = await signIn(platform, 'lucas');
    const post = (await amelia.feed.get({ tab: 'following' })).data.find((p) => p.author.handle === 'lucas')!;
    const once = await amelia.posts.react(post.id, 'like');
    const twice = await amelia.posts.react(post.id, 'love');
    expect(twice.reaction).toBe('love');
    expect(twice.counts.reactions).toBe(once.counts.reactions);
    expect(twice.counts.reactions_by_type.love).toBe((once.counts.reactions_by_type.love ?? 0) + 1);
    await amelia.users.block(lucasAuth.user.account.id);
    await expectApiError(amelia.posts.get(post.id), 404, 'not_found');
    const lucasFeed = await lucas.feed.get({ tab: 'for_you', limit: 50 });
    expect(lucasFeed.data.some((p) => p.author.handle === 'amelia')).toBe(false);
  });

  it('requires and honours Idempotency-Key on post creation', async () => {
    const { api } = await signIn(platform, 'amelia');
    const body = { kind: 'text' as const, body: 'Hello Rio', visibility: 'public' as const, location_precision: 'none' as const };
    const key = '0193a000-0000-7000-8000-000000000001';
    const a = await api.posts.create(body, key);
    const b = await api.posts.create(body, key);
    expect(b.id).toBe(a.id);
    await expectApiError(api.posts.create({ ...body, body: 'Different' }, key), 409, 'idempotency_key_reused');
  });

  it('marks public posts indexable only when the author opted into search indexing (PROF-008)', async () => {
    const anon = clientFor(platform);
    const page = await anon.publicPosts.list({ limit: 100 });
    const byAuthor = (handle: string) => page.data.filter((p) => p.author.handle === handle);
    expect(byAuthor('amelia').every((p) => p.indexable === true)).toBe(true);
    expect(byAuthor('noah').length).toBeGreaterThan(0);
    expect(byAuthor('noah').every((p) => p.indexable === false)).toBe(true); // noah never opted in

    const { api: amelia } = await signIn(platform, 'amelia');
    await amelia.me.updatePrivacy({ search_engine_indexing: false });
    const after = await anon.publicPosts.list({ limit: 100 });
    expect(after.data.filter((p) => p.author.handle === 'amelia').every((p) => p.indexable === false)).toBe(true);
  });

  it('derives staff permissions from the cumulative role ladder and none for travelers', async () => {
    const { result: moderator } = await signIn(platform, 'priya.mod');
    expect(moderator.user.permissions).toEqual(expect.arrayContaining(['moderation.reports.manage', 'users.suspend', 'users.read']));
    expect(moderator.user.permissions).not.toContain('billing.configure');
    const { result: traveler } = await signIn(platform, 'amelia');
    expect(traveler.user.permissions).toEqual([]);
    expect(traveler.user.account.restrictions).toEqual([]);
  });

  it('does not simulate payments, AI or chat', async () => {
    const { api } = await signIn(platform, 'lucas');
    await expectApiError(api.billing.products(), 503, 'feature_not_available_in_mock');
    await expectApiError(api.realtime.ticket(), 503, 'feature_not_available_in_mock');
    const raw = await platform.transport.send({ method: 'POST', path: '/v1/ai/itineraries', body: {} });
    expect(raw.status).toBe(503);
    expect(raw.headers['x-tb-mock']).toBe('1');
  });
});
