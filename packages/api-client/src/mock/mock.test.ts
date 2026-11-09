import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
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

const REGISTER = { client: 'web' as const, accepted_terms_version: '2026-11-01', accepted_privacy_version: '2026-11-01' };

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
    const { id_token } = await anon.auth.devIdpToken({ sub: 'new:1', email: 'new.person@example.com', name: 'New Person' });
    await expectApiError(anon.auth.register({ ...REGISTER, id_token, birth_date: '2012-01-01', locale: 'en' }), 403, 'age_restricted');
    const result = await anon.auth.register({ ...REGISTER, id_token, birth_date: '1995-06-01', locale: 'pt-BR' });
    expect(result.is_new_user).toBe(true);
    expect(result.user.onboarding_completed).toBe(false);
    expect(result.user.preferences.ui_locale).toBe('pt-BR');
    expect(result.user.privacy.discovery_enabled).toBe(false);
    expect(result.user.privacy.location_consent).toBeNull();
  });

  it('requires consent to the current legal versions served by client-config', async () => {
    const anon = clientFor(platform);
    await expectApiError(anon.config.get({ platform: 'web', app_version: 'latest' }), 422, 'validation_failed');
    const config = await anon.config.get({ platform: 'web', app_version: '0.1.0' });
    expect(config.legal.terms_version).toBe('2026-11-01');
    const { id_token } = await anon.auth.devIdpToken({ sub: 'new:old-terms', email: 'old.terms@example.com' });
    const error = await anon.auth.register({ ...REGISTER, id_token, birth_date: '1990-01-01', locale: 'en', accepted_terms_version: '2025-01-01' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe('consent_required');
    expect((error as ApiError).problem.terms_version).toBe('2026-11-01');
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

  it('accepts sessions created by another instance with the same key (serverless demo)', async () => {
    const instanceA = createMockPlatform({ now, tokenSecret: 'shared-demo-key-0123456789abcdef0123' });
    const instanceB = createMockPlatform({ now, tokenSecret: 'shared-demo-key-0123456789abcdef0123' });
    const other = createMockPlatform({ now, tokenSecret: 'a-different-key-0123456789abcdef01234' });

    const { result } = await signIn(instanceA, 'amelia');
    const onB = clientFor(instanceB, result.tokens.access_token);
    expect((await onB.me.get()).profile.handle).toBe('amelia');
    const rotated = await clientFor(instanceB).auth.refresh({ refresh_token: result.tokens.refresh_token });
    expect((await clientFor(instanceA, rotated.access_token).me.get()).profile.handle).toBe('amelia');
    await expectApiError(clientFor(other, result.tokens.access_token).me.get(), 401, 'unauthenticated');

    // A registered (non-seeded) user is rebuilt from the token's minimal identity.
    const anon = clientFor(instanceA);
    const { id_token } = await anon.auth.devIdpToken({ sub: 'new:x', email: 'x.traveler@example.com', name: 'X Traveler' });
    const reg = await anon.auth.register({ ...REGISTER, id_token, birth_date: '1990-01-01', locale: 'fr' });
    const meOnB = await clientFor(instanceB, reg.tokens.access_token).me.get();
    expect(meOnB.profile.display_name).toBe('X Traveler');
    expect(meOnB.preferences.ui_locale).toBe('fr');
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
    // Slugs follow the platform seed rule, so switching to the live API keeps them.
    expect(tokyo.slug).toBe('tokyo-jp');
    expect((await pt.destinations.lookup('brazil/rio-de-janeiro/copacabana')).slug).toBe('copacabana-rio-de-janeiro-br');
  });

  it('lists destinations anonymously with filters and a stable slug order for sitemaps', async () => {
    const anon = clientFor(platform);
    const cities = await anon.destinations.list({ kind: ['city'], continent: 'europe', sort: 'slug', limit: 100 });
    expect(cities.data.length).toBeGreaterThan(3);
    expect(cities.data.every((d) => d.kind === 'city' && d.continent === 'europe')).toBe(true);
    const paths = cities.data.map((d) => d.path);
    expect([...paths].sort()).toEqual(paths);
  });

  it('gives every city and country an openly licensed, credited cover photo that the web app ships', async () => {
    const anon = clientFor(platform);
    const all = await anon.destinations.list({ kind: ['country', 'city'], sort: 'slug', limit: 100 });
    expect(all.data.length).toBeGreaterThan(20);
    for (const d of all.data) {
      const cover = d.cover;
      expect(cover, d.path).toBeTruthy();
      expect(cover).toMatchObject({ kind: 'image', status: 'ready' });
      expect(cover?.alt_text?.length, d.path).toBeGreaterThan(10);
      expect(cover?.attribution?.text, d.path).toMatch(/\S \/ Wikimedia Commons$/);
      expect(cover?.attribution?.license, d.path).toMatch(/^(CC0|CC BY(-SA)? \d\.\d)$/);
      expect(cover?.attribution?.url, d.path).toMatch(/^https:\/\/commons\.wikimedia\.org\/wiki\/File:/);
      const file = fileURLToPath(new URL(`../../../../apps/web/public${cover?.url}`, import.meta.url));
      expect(existsSync(file), `${d.path} → ${cover?.url}`).toBe(true);
    }
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

  it('records shares of publicly listed posts and refuses others (403)', async () => {
    const { api: amelia } = await signIn(platform, 'amelia');
    const feed = await amelia.feed.get({ tab: 'for_you', limit: 50 });
    const publicPost = feed.data.find((p) => p.visibility === 'public')!;
    const link = await amelia.posts.share(publicPost.id);
    expect(link.url).toMatch(new RegExp(`/stories/${publicPost.id}$`));
    expect((await amelia.posts.get(publicPost.id)).counts.shares).toBe(publicPost.counts.shares + 1);
    const privateNote = feed.data.find((p) => p.body.includes('reef-safe'))!;
    await expectApiError(amelia.posts.share(privateNote.id), 403, 'forbidden');
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
    expect(nearby.context.destination?.slug).toBe('rio-de-janeiro-br');
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

  it('lists the accounts I blocked, and unblocking removes them from the list', async () => {
    const { api: amelia } = await signIn(platform, 'amelia');
    const { result: lucasAuth } = await signIn(platform, 'lucas');
    expect((await amelia.users.blocks()).data).toEqual([]);
    await amelia.users.block(lucasAuth.user.account.id);
    await amelia.users.block(lucasAuth.user.account.id); // idempotent
    const listed = await amelia.users.blocks();
    expect(listed.data.map((u) => u.handle)).toEqual(['lucas']);
    expect(listed.page).toEqual({ next_cursor: null, has_more: false });
    await amelia.users.unblock(lucasAuth.user.account.id);
    expect((await amelia.users.blocks()).data).toEqual([]);
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
