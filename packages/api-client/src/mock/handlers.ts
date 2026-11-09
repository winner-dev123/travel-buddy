import {
  CONTINENTS,
  FEED_TABS,
  POST_KINDS,
  REACTION_TYPES,
  REPORT_REASONS,
  SUPPORTED_LOCALES,
  TRAVEL_STYLES,
  type AuthResult,
  type DestinationKind,
  type FeedSource,
  type FeedTab,
  type LocaleCode,
  type PostKind,
  type ReactionType,
  type SessionTokens,
  type TravelStyle,
} from '@travelbuddy/domain-types';
import { ageOn, commentSchema, createPostSchema, distanceKm, MINIMUM_AGE, parseNearParam, roundCoordinate } from '@travelbuddy/validation';
import type { HttpMethod } from '../core/types';
import {
  ACCESS_TTL_MS,
  defaultPreferences,
  defaultPrivacy,
  DEV_TOKEN_TTL_MS,
  REFRESH_REUSE_LEEWAY_MS,
  REFRESH_TTL_MS,
  type DestinationRecord,
  type MockDb,
  type PostRecord,
  type SessionRecord,
  type TokenPair,
  type UserRecord,
} from './db';
import { randomToken, uuidv7 } from './ids';
import { signMockToken, verifyMockToken, type MockTokenClaims } from './tokens';
import { MockHttpError, notFound, notInMock, problem, unauthenticated, validation } from './problems';
import { Router } from './router';

export interface MockContext {
  db: MockDb;
  method: HttpMethod;
  params: Record<string, string>;
  query: (name: string) => string | undefined;
  body: Record<string, unknown>;
  headers: Record<string, string>;
  locale: LocaleCode;
  now: number;
  /** Resolves the Bearer token; throws 401 when missing, unknown or expired. */
  auth: () => { user: UserRecord; session: SessionRecord };
  /** Like `auth` but returns null for anonymous requests (optional-auth endpoints). */
  optionalAuth: () => { user: UserRecord; session: SessionRecord } | null;
}

export interface MockResult {
  status: number;
  body?: unknown;
}

type Handler = (ctx: MockContext) => MockResult;

/** Current legal document versions (the platform serves them via client-config; doc 05). */
export const LEGAL_VERSION = '2026-11-01';

const ok = (body: unknown): MockResult => ({ status: 200, body });
const created = (body: unknown): MockResult => ({ status: 201, body });
const noContent = (): MockResult => ({ status: 204 });

// ---- helpers ---------------------------------------------------------------------------------

function str(body: Record<string, unknown>, key: string): string | undefined {
  const v = body[key];
  return typeof v === 'string' ? v : undefined;
}

function intParam(value: string | undefined, fallback: number, min: number, max: number): number {
  const n = Number(value);
  if (value === undefined || !Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}

function encodeCursor(offset: number, fingerprint: string): string {
  return btoa(JSON.stringify({ o: offset, f: fingerprint })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function decodeCursor(cursor: string | undefined, fingerprint: string): number {
  if (!cursor) return 0;
  try {
    const json = JSON.parse(atob(cursor.replace(/-/g, '+').replace(/_/g, '/'))) as { o?: unknown; f?: unknown };
    if (typeof json.o === 'number' && json.f === fingerprint && json.o >= 0) return json.o;
  } catch {
    // fall through
  }
  throw validation('cursor', 'invalid', 'The cursor is invalid or belongs to a different query.');
}

function paginate<T>(items: T[], ctx: MockContext, fingerprint: string, defaultLimit = 20) {
  const limit = intParam(ctx.query('limit'), defaultLimit, 1, 100);
  const offset = decodeCursor(ctx.query('cursor'), fingerprint);
  const hasMore = offset + limit < items.length;
  return {
    data: items.slice(offset, offset + limit),
    page: { next_cursor: hasMore ? encodeCursor(offset + limit, fingerprint) : null, has_more: hasMore },
  };
}

function normalize(s: string): string {
  return s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
}

function listParam(value: string | undefined): string[] {
  return (value ?? '').split(',').map((s) => s.trim()).filter(Boolean);
}

function destinationOr404(db: MockDb, id: string | undefined): DestinationRecord {
  const rec = id ? db.destinations.get(id) : undefined;
  if (!rec) throw notFound();
  return rec;
}

function mustDestination(db: MockDb, id: unknown, field: string): DestinationRecord {
  const rec = typeof id === 'string' ? db.destinations.get(id) : undefined;
  if (!rec) throw validation(field, 'unknown', 'Unknown destination.');
  return rec;
}

function visiblePostOr404(ctx: MockContext, user: UserRecord): PostRecord {
  const post = ctx.db.posts.get(ctx.params.postId ?? '');
  if (!post || !ctx.db.canView(user, post)) throw notFound();
  return post;
}

function nearestCity(db: MockDb, point: { lat: number; lng: number }, maxKm = 50): DestinationRecord | null {
  let best: DestinationRecord | null = null;
  let bestKm = Infinity;
  for (const d of db.destinations.values()) {
    if (d.f.kind !== 'city' || !d.f.center) continue;
    const km = distanceKm(point, d.f.center);
    if (km < bestKm && km <= maxKm) {
      best = d;
      bestKm = km;
    }
  }
  return best;
}

function issueTokens(db: MockDb, now: number, user: UserRecord, sessionId: string): TokenPair {
  const persona = user.identitySub.startsWith('persona:');
  // Non-seeded (registered) users carry minimal identity so another serverless instance can rebuild them.
  const id = persona ? undefined : { h: user.handle, n: user.display_name, m: user.email, l: user.preferences.ui_locale };
  const accessExpiresAt = now + ACCESS_TTL_MS;
  const refreshExpiresAt = now + REFRESH_TTL_MS;
  return {
    access: signMockToken({ k: 'a', u: user.id, s: sessionId, e: accessExpiresAt, id }, db.tokenSecret),
    accessExpiresAt,
    refresh: signMockToken({ k: 'r', u: user.id, s: sessionId, e: refreshExpiresAt, id }, db.tokenSecret),
    refreshExpiresAt,
  };
}

/**
 * Cross-instance support for serverless demos: rebuilds a user and session that were created by
 * another instance, from a verified token. Seeded personas exist in every instance already.
 */
export function rebuildFromClaims(db: MockDb, claims: MockTokenClaims, token: string, now: number): { user: UserRecord; session: SessionRecord } | null {
  let user = db.users.get(claims.u);
  if (!user && claims.id) {
    user = {
      id: claims.u,
      identitySub: `rebuilt:${claims.u}`,
      handle: claims.id.h,
      email: claims.id.m,
      display_name: claims.id.n,
      bio: null,
      travel_styles: [],
      home_country_code: null,
      languages: [],
      created_at: now,
      updated_at: now,
      roles: [],
      status: 'active',
      onboarding_completed: true,
      preferences: defaultPreferences((SUPPORTED_LOCALES as readonly string[]).includes(claims.id.l) ? (claims.id.l as LocaleCode) : 'en'),
      privacy: defaultPrivacy(),
      browsePath: null,
      premium: false,
      birth_year: null,
    };
    db.users.set(user.id, user);
  }
  if (!user) return null;
  let session = db.sessions.get(claims.s);
  if (!session) {
    const pair: TokenPair = claims.k === 'r'
      ? { access: '', accessExpiresAt: 0, refresh: token, refreshExpiresAt: claims.e }
      : { access: token, accessExpiresAt: claims.e, refresh: '', refreshExpiresAt: claims.e };
    session = { id: claims.s, userId: user.id, client: 'web', createdAt: now, lastSeenAt: now, current: pair, previous: null, revoked: false };
    db.sessions.set(session.id, session);
  }
  return { user, session };
}

function sessionTokens(db: MockDb, session: SessionRecord, pair: TokenPair): SessionTokens {
  return {
    token_type: 'Bearer',
    access_token: pair.access,
    access_token_expires_at: db.iso(pair.accessExpiresAt),
    refresh_token: pair.refresh,
    refresh_token_expires_at: db.iso(pair.refreshExpiresAt),
    session_id: session.id,
  };
}

function startSession(ctx: MockContext, user: UserRecord): SessionRecord {
  const sessionId = uuidv7(ctx.now);
  const pair = issueTokens(ctx.db, ctx.now, user, sessionId);
  const client = str(ctx.body, 'client');
  const session: SessionRecord = {
    id: sessionId,
    userId: user.id,
    client: client === 'ios' || client === 'android' ? client : 'web',
    createdAt: ctx.now,
    lastSeenAt: ctx.now,
    current: pair,
    previous: null,
    revoked: false,
  };
  ctx.db.sessions.set(session.id, session);
  ctx.db.accessTokens.set(pair.access, { sessionId: session.id, expiresAt: pair.accessExpiresAt });
  return session;
}

function verifyDevToken(ctx: MockContext) {
  const token = str(ctx.body, 'id_token');
  const identity = token ? ctx.db.devIdentities.get(token) : undefined;
  if (!identity) throw problem(401, 'token_invalid', 'The ID token is invalid.');
  if (identity.expiresAt < ctx.now) throw problem(401, 'token_expired', 'The ID token has expired.');
  return identity;
}

function uniqueHandle(db: MockDb, base: string): string {
  const cleaned = normalize(base).replace(/[^a-z0-9._]/g, '').replace(/^[._]+|[._]+$/g, '').slice(0, 24) || 'traveler';
  let handle = cleaned.length >= 3 ? cleaned : `${cleaned}traveler`;
  let i = 1;
  while (db.findUserByHandle(handle)) handle = `${cleaned}${++i}`;
  return handle;
}

function asEnumList<T extends string>(value: unknown, allowed: readonly T[], max: number): T[] | null {
  if (!Array.isArray(value) || value.length > max) return null;
  if (!value.every((v) => typeof v === 'string' && (allowed as readonly string[]).includes(v))) return null;
  return [...new Set(value as T[])];
}

function bool(body: Record<string, unknown>, key: string, apply: (v: boolean) => void) {
  if (key in body) {
    if (typeof body[key] !== 'boolean') throw validation(key, 'invalid', `${key} must be a boolean.`);
    apply(body[key]);
  }
}

function oneOf<T extends string>(body: Record<string, unknown>, key: string, allowed: readonly T[], apply: (v: T) => void) {
  if (key in body) {
    if (!(allowed as readonly unknown[]).includes(body[key])) throw validation(key, 'invalid', `Invalid ${key}.`);
    apply(body[key] as T);
  }
}

// ---- router ----------------------------------------------------------------------------------

export function buildRouter(): Router<Handler> {
  const r = new Router<Handler>();

  r.add('GET', '/v1/client-config', (ctx) => {
    if (!['web', 'ios', 'android'].includes(ctx.query('platform') ?? '')) throw validation('platform', 'required', 'platform must be ios, android or web.');
    if (!/^\d+\.\d+\.\d+$/.test(ctx.query('app_version') ?? '')) throw validation('app_version', 'required', 'app_version must be x.y.z.');
    return ok({
      min_supported_version: '0.0.0',
      update_required: false,
      supported_locales: [...SUPPORTED_LOCALES],
      default_locale: 'en',
      // Features that are not built yet are off; values are global and UI-only.
      feature_flags: { traveler_discovery: false, travel_groups: false, ai_itineraries: false, post_translation: false },
      web_push_vapid_public_key: null,
      legal: {
        terms_version: LEGAL_VERSION,
        privacy_version: LEGAL_VERSION,
        terms_url: 'https://travelbuddy.example/legal/terms',
        privacy_url: 'https://travelbuddy.example/legal/privacy',
      },
      minimum_age: MINIMUM_AGE,
    });
  });

  // Dev IdP (development/test only on the real backend).
  r.add('POST', '/v1/dev/idp/token', (ctx) => {
    const sub = str(ctx.body, 'sub');
    const email = str(ctx.body, 'email');
    if (!sub) throw validation('sub', 'required', 'sub is required.');
    if (!email || !email.includes('@')) throw validation('email', 'invalid', 'A valid email is required.');
    const token = randomToken('mock-dev-idp');
    const expiresAt = ctx.now + DEV_TOKEN_TTL_MS;
    ctx.db.devIdentities.set(token, { sub, email, email_verified: ctx.body.email_verified !== false, name: str(ctx.body, 'name') ?? null, expiresAt });
    return ok({ id_token: token, expires_at: ctx.db.iso(expiresAt) });
  });

  // ---- identity ------------------------------------------------------------------------------
  r.add('POST', '/v1/auth/login', (ctx) => {
    const identity = verifyDevToken(ctx);
    const userId = ctx.db.usersBySub.get(identity.sub);
    const user = userId ? ctx.db.users.get(userId) : undefined;
    if (!user) throw notFound('No account exists for this identity. Register first.');
    if (user.status === 'suspended') throw problem(403, 'account_suspended', 'This account is suspended.');
    const session = startSession(ctx, user);
    return ok({ tokens: sessionTokens(ctx.db, session, session.current), user: ctx.db.me(user, ctx.locale), is_new_user: false } satisfies AuthResult);
  });

  r.add('POST', '/v1/auth/register', (ctx) => {
    const identity = verifyDevToken(ctx);
    if (ctx.db.usersBySub.has(identity.sub)) throw problem(409, 'conflict', 'An account already exists for this identity.');
    const birth = str(ctx.body, 'birth_date');
    const age = birth ? ageOn(birth, new Date(ctx.now)) : null;
    if (age === null) throw validation('birth_date', 'invalid', 'birth_date must be YYYY-MM-DD.');
    if (age < MINIMUM_AGE) throw problem(403, 'age_restricted', `You must be at least ${MINIMUM_AGE} to use Travel Buddy.`);
    // Like the platform: consent must be to the CURRENT legal versions, otherwise 403 consent_required
    // with the versions the client should show the user again.
    if (str(ctx.body, 'accepted_terms_version') !== LEGAL_VERSION || str(ctx.body, 'accepted_privacy_version') !== LEGAL_VERSION) {
      throw new MockHttpError({
        type: 'https://errors.travelbuddy.app/consent_required',
        title: 'Consent to the current terms is required',
        status: 403,
        code: 'consent_required',
        detail: 'Accept the current terms of service and privacy policy.',
        terms_version: LEGAL_VERSION,
        privacy_version: LEGAL_VERSION,
      });
    }
    const requested = str(ctx.body, 'locale');
    const locale: LocaleCode = (SUPPORTED_LOCALES as readonly string[]).includes(requested ?? '') ? (requested as LocaleCode) : 'en';
    const user: UserRecord = {
      id: uuidv7(ctx.now),
      identitySub: identity.sub,
      handle: uniqueHandle(ctx.db, identity.email.split('@')[0] ?? 'traveler'),
      email: identity.email,
      display_name: (identity.name ?? '').trim().slice(0, 50) || 'New traveler',
      bio: null,
      travel_styles: [],
      home_country_code: null,
      languages: [],
      created_at: ctx.now,
      updated_at: ctx.now,
      roles: [],
      status: 'active',
      onboarding_completed: false,
      preferences: defaultPreferences(locale),
      privacy: defaultPrivacy(),
      browsePath: null,
      premium: false,
      birth_year: Number(birth?.slice(0, 4)),
    };
    ctx.db.users.set(user.id, user);
    ctx.db.usersBySub.set(user.identitySub, user.id);
    const session = startSession(ctx, user);
    return created({ tokens: sessionTokens(ctx.db, session, session.current), user: ctx.db.me(user, ctx.locale), is_new_user: true } satisfies AuthResult);
  });

  r.add('POST', '/v1/auth/refresh', (ctx) => {
    const presented = str(ctx.body, 'refresh_token');
    if (!presented) throw unauthenticated();
    const claims = verifyMockToken(presented, ctx.db.tokenSecret);
    if (!claims || claims.k !== 'r') throw unauthenticated();
    if (claims.e < ctx.now) throw problem(401, 'session_revoked', 'The session has expired.');
    const known = ctx.db.sessions.get(claims.s);
    if (known?.revoked) throw unauthenticated();
    if (!known || (known.current.refresh !== presented && known.previous?.refresh !== presented)) {
      // Session created or last rotated by another (serverless) instance: accept the signed token,
      // rebuild locally and rotate from here. In-instance reuse detection below still applies.
      const rebuilt = rebuildFromClaims(ctx.db, claims, presented, ctx.now);
      if (!rebuilt) throw unauthenticated();
      rebuilt.session.current = { ...rebuilt.session.current, refresh: presented, refreshExpiresAt: claims.e };
    }
    for (const session of ctx.db.sessions.values()) {
      if (session.revoked) continue;
      if (session.current.refresh === presented) {
        if (session.current.refreshExpiresAt < ctx.now) throw problem(401, 'session_revoked', 'The session has expired.');
        const owner = ctx.db.users.get(session.userId);
        if (!owner) throw unauthenticated();
        const next = issueTokens(ctx.db, ctx.now, owner, session.id);
        session.previous = { refresh: presented, rotatedAt: ctx.now, successor: next };
        session.current = next;
        session.lastSeenAt = ctx.now;
        ctx.db.accessTokens.set(next.access, { sessionId: session.id, expiresAt: next.accessExpiresAt });
        return ok(sessionTokens(ctx.db, session, next));
      }
      if (session.previous?.refresh === presented) {
        if (ctx.now - session.previous.rotatedAt <= REFRESH_REUSE_LEEWAY_MS) {
          // ADR-0011 leeway: parallel refreshes from one browser get the same successor.
          return ok(sessionTokens(ctx.db, session, session.previous.successor));
        }
        session.revoked = true; // reuse after the leeway → revoke the whole family
        throw problem(401, 'refresh_token_reused', 'Refresh token reuse detected; the session was revoked.');
      }
    }
    throw unauthenticated();
  });

  r.add('POST', '/v1/auth/logout', (ctx) => {
    const { user, session } = ctx.auth();
    if (ctx.body.all_sessions === true) {
      for (const s of ctx.db.sessions.values()) if (s.userId === user.id) s.revoked = true;
    } else {
      session.revoked = true;
    }
    return noContent();
  });

  // ---- me ------------------------------------------------------------------------------------
  r.add('GET', '/v1/users/me', (ctx) => ok(ctx.db.me(ctx.auth().user, ctx.locale)));

  r.add('PATCH', '/v1/users/me', (ctx) => {
    const { user } = ctx.auth();
    const b = ctx.body;
    if ('display_name' in b) {
      const v = typeof b.display_name === 'string' ? b.display_name.trim() : '';
      if (v.length < 1 || v.length > 50) throw validation('display_name', 'invalid', 'Display name must be 1–50 characters.');
      user.display_name = v;
    }
    if ('bio' in b) {
      if (b.bio !== null && (typeof b.bio !== 'string' || b.bio.length > 300)) throw validation('bio', 'too_long', 'Bio must be at most 300 characters.');
      user.bio = (b.bio as string | null) || null;
    }
    if ('travel_styles' in b) {
      const styles = asEnumList<TravelStyle>(b.travel_styles, TRAVEL_STYLES, 9);
      if (!styles) throw validation('travel_styles', 'invalid', 'Unknown travel style.');
      user.travel_styles = styles;
    }
    if ('home_country_code' in b) {
      const cc = b.home_country_code;
      if (cc !== null && (typeof cc !== 'string' || !/^[A-Z]{2}$/.test(cc))) throw validation('home_country_code', 'invalid', 'Use an ISO 3166-1 alpha-2 code.');
      user.home_country_code = cc as string | null;
    }
    if ('languages_spoken' in b) {
      if (!Array.isArray(b.languages_spoken) || b.languages_spoken.length > 10) throw validation('languages_spoken', 'invalid', 'Invalid languages.');
      user.languages = (b.languages_spoken as unknown[]).filter((l): l is string => typeof l === 'string');
    }
    user.updated_at = ctx.now;
    return ok(ctx.db.me(user, ctx.locale));
  });

  r.add('GET', '/v1/users/me/preferences', (ctx) => ok({ ...ctx.auth().user.preferences }));
  r.add('PATCH', '/v1/users/me/preferences', (ctx) => {
    const { user } = ctx.auth();
    const p = user.preferences;
    oneOf(ctx.body, 'ui_locale', SUPPORTED_LOCALES, (v) => (p.ui_locale = v));
    oneOf(ctx.body, 'distance_unit', ['km', 'mi'] as const, (v) => (p.distance_unit = v));
    bool(ctx.body, 'auto_translate', (v) => (p.auto_translate = v));
    if (typeof ctx.body.time_zone === 'string') p.time_zone = ctx.body.time_zone;
    return ok({ ...p });
  });

  r.add('GET', '/v1/users/me/privacy', (ctx) => ok({ ...ctx.auth().user.privacy }));
  r.add('PATCH', '/v1/users/me/privacy', (ctx) => {
    const { user } = ctx.auth();
    const p = user.privacy;
    bool(ctx.body, 'discovery_enabled', (v) => {
      p.discovery_enabled = v;
      // Turning discovery on records the consent version (doc 08); off keeps history server-side.
      if (v && !p.discovery_consent) p.discovery_consent = { version: '2026-11', granted_at: ctx.db.iso(ctx.now) };
    });
    bool(ctx.body, 'search_engine_indexing', (v) => (p.search_engine_indexing = v));
    bool(ctx.body, 'show_trips_on_profile', (v) => (p.show_trips_on_profile = v));
    bool(ctx.body, 'read_receipts_enabled', (v) => (p.read_receipts_enabled = v));
    oneOf(ctx.body, 'discovery_granularity', ['city', 'neighborhood'] as const, (v) => (p.discovery_granularity = v));
    oneOf(ctx.body, 'connection_requests_from', ['everyone', 'shared_context', 'nobody'] as const, (v) => (p.connection_requests_from = v));
    oneOf(ctx.body, 'profile_visibility', ['public', 'connections'] as const, (v) => (p.profile_visibility = v));
    oneOf(ctx.body, 'post_location_default', ['none', 'destination', 'place'] as const, (v) => (p.post_location_default = v));
    return ok({ ...p });
  });

  r.add('GET', '/v1/users/me/browse-destination', (ctx) => {
    const { user } = ctx.auth();
    const rec = user.browsePath ? ctx.db.destinationsByPath.get(user.browsePath) : undefined;
    if (!rec) throw notFound('No browse destination selected.');
    return ok({ destination: ctx.db.destinationSummary(rec, ctx.locale), selected_at: ctx.db.iso(ctx.now) });
  });
  r.add('PUT', '/v1/users/me/browse-destination', (ctx) => {
    const { user } = ctx.auth();
    const rec = mustDestination(ctx.db, ctx.body.destination_id, 'destination_id');
    user.browsePath = rec.path;
    return ok({ destination: ctx.db.destinationSummary(rec, ctx.locale), selected_at: ctx.db.iso(ctx.now) });
  });
  r.add('DELETE', '/v1/users/me/browse-destination', (ctx) => {
    ctx.auth().user.browsePath = null;
    return noContent();
  });

  r.add('POST', '/v1/users/me/onboarding/complete', (ctx) => {
    const { user } = ctx.auth();
    user.onboarding_completed = true;
    return ok(ctx.db.me(user, ctx.locale));
  });

  r.add('GET', '/v1/users/me/bookmarks', (ctx) => {
    const { user } = ctx.auth();
    const posts = [...ctx.db.posts.values()]
      .filter((p) => ctx.db.bookmarks.has(`${user.id}:${p.id}`) && ctx.db.canView(user, p))
      .sort((a, b) => b.createdAt - a.createdAt)
      .map((p) => ctx.db.post(p, user, ctx.locale));
    return ok(paginate(posts, ctx, `bookmarks:${user.id}`));
  });

  // ---- destinations (optional auth) ---------------------------------------------------------
  r.add('GET', '/v1/destinations', (ctx) => {
    const kinds = listParam(ctx.query('kind')) as DestinationKind[];
    const country = ctx.query('country')?.toUpperCase();
    const continent = ctx.query('continent');
    const featured = ctx.query('featured');
    const sort = ctx.query('sort') ?? 'popularity';
    if (continent && !(CONTINENTS as readonly string[]).includes(continent)) throw validation('continent', 'invalid', 'Unknown continent.');
    if (sort !== 'popularity' && sort !== 'slug') throw validation('sort', 'invalid', 'Unknown sort.');
    let items = [...ctx.db.destinations.values()];
    if (kinds.length) items = items.filter((d) => kinds.includes(d.f.kind));
    if (country) items = items.filter((d) => d.f.country_code === country);
    if (continent) items = items.filter((d) => d.f.continent === continent);
    if (featured === 'true') items = items.filter((d) => d.f.featured);
    items.sort(sort === 'slug' ? (a, b) => a.path.localeCompare(b.path) : (a, b) => ctx.db.popularity(b) - ctx.db.popularity(a) || a.path.localeCompare(b.path));
    return ok(paginate(items.map((d) => ctx.db.destinationSummary(d, ctx.locale)), ctx, `dl:${kinds.join(',')}:${country}:${continent}:${featured}:${sort}`, 24));
  });

  r.add('GET', '/v1/destinations/featured', (ctx) => {
    const items = [...ctx.db.destinations.values()]
      .filter((d) => d.f.featured)
      .sort((a, b) => ctx.db.popularity(b) - ctx.db.popularity(a))
      .map((d) => ctx.db.destinationSummary(d, ctx.locale));
    return ok(paginate(items, ctx, 'featured', 12));
  });

  r.add('GET', '/v1/destinations/search', (ctx) => {
    const q = normalize((ctx.query('q') ?? '').trim());
    if (q.length < 2 || q.length > 80) throw validation('q', 'invalid', 'q must be 2–80 characters.');
    const kinds = listParam(ctx.query('kind'));
    const country = ctx.query('country')?.toUpperCase();
    const limit = intParam(ctx.query('limit'), 8, 1, 100);
    const scored: { d: DestinationRecord; score: number }[] = [];
    for (const d of ctx.db.destinations.values()) {
      if (kinds.length && !kinds.includes(d.f.kind)) continue;
      if (country && d.f.country_code !== country) continue;
      const names = Object.values(d.f.name).map((n) => normalize(n as string));
      const best = Math.max(...names.map((n) => (n.startsWith(q) ? 3 : n.includes(q) ? 1 : 0)));
      if (best > 0) scored.push({ d, score: best + (d.f.kind === 'city' ? 1 : d.f.kind === 'country' ? 0.5 : 0) });
    }
    scored.sort((a, b) => b.score - a.score || a.d.path.localeCompare(b.d.path));
    return ok({ data: scored.slice(0, limit).map((s) => ctx.db.destinationSummary(s.d, ctx.locale)), page: { next_cursor: null, has_more: false } });
  });

  r.add('GET', '/v1/destinations/lookup', (ctx) => {
    const path = (ctx.query('path') ?? '').replace(/^\/+|\/+$/g, '').toLowerCase();
    const rec = ctx.db.destinationsByPath.get(path);
    if (!rec) throw notFound();
    return ok(ctx.db.destinationDetail(rec, ctx.locale));
  });

  r.add('GET', '/v1/destinations/resolve', (ctx) => {
    ctx.auth();
    const near = parseNearParam(ctx.query('near'));
    if (!near) throw validation('near', 'invalid', 'near must be "lat,lng".');
    // Round, resolve, discard (doc 02 §6). The point is never stored or echoed.
    const city = nearestCity(ctx.db, near);
    if (!city) throw problem(422, 'location_unresolvable', 'No supported destination near this location yet.');
    return ok(ctx.db.destinationDetail(city, ctx.locale));
  });

  r.add('GET', '/v1/destinations/:destinationId/children', (ctx) => {
    const rec = destinationOr404(ctx.db, ctx.params.destinationId);
    const kids = ctx.db.childrenOf(rec).sort((a, b) => ctx.db.popularity(b) - ctx.db.popularity(a)).map((d) => ctx.db.destinationSummary(d, ctx.locale));
    return ok(paginate(kids, ctx, `children:${rec.id}`, 50));
  });

  r.add('GET', '/v1/destinations/:destinationId/guides', (ctx) => {
    const rec = destinationOr404(ctx.db, ctx.params.destinationId);
    return ok({ data: rec.f.overview ? [ctx.db.guideSummary(rec, ctx.locale)] : [] });
  });

  r.add('GET', '/v1/destinations/:destinationId', (ctx) => ok(ctx.db.destinationDetail(destinationOr404(ctx.db, ctx.params.destinationId), ctx.locale)));

  // Free guides are readable anonymously (contract: security [{}, bearer]).
  r.add('GET', '/v1/guides/:guideId', (ctx) => {
    const rec = ctx.db.guideRecordById(ctx.params.guideId ?? '');
    if (!rec) throw notFound();
    return ok(ctx.db.guide(rec, ctx.locale));
  });

  // ---- public stories (anonymous) ------------------------------------------------------------
  r.add('GET', '/v1/public/posts', (ctx) => {
    const destId = ctx.query('destination_id');
    const dest = destId ? ctx.db.destinations.get(destId) : undefined;
    if (destId && !dest) throw validation('destination_id', 'unknown', 'Unknown destination.');
    const kinds = listParam(ctx.query('category')) as PostKind[];
    const posts = [...ctx.db.posts.values()]
      .filter((p) => p.visibility === 'public' && ctx.db.canView(null, p))
      .filter((p) => !dest || ctx.db.isWithin(p.destinationPath, dest.path))
      .filter((p) => kinds.length === 0 || kinds.includes(p.kind))
      .sort((a, b) => b.createdAt - a.createdAt)
      .map((p) => ctx.db.publicPost(p, ctx.locale));
    return ok(paginate(posts, ctx, `public:${destId ?? ''}:${kinds.join(',')}`, 12));
  });

  r.add('GET', '/v1/public/posts/:postId', (ctx) => {
    const post = ctx.db.posts.get(ctx.params.postId ?? '');
    if (!post || post.visibility !== 'public' || !ctx.db.canView(null, post)) throw notFound();
    return ok(ctx.db.publicPost(post, ctx.locale));
  });

  // ---- feed ----------------------------------------------------------------------------------
  r.add('GET', '/v1/feed', (ctx) => {
    const { user } = ctx.auth();
    const tab = (ctx.query('tab') ?? 'for_you') as FeedTab;
    if (!(FEED_TABS as readonly string[]).includes(tab)) throw validation('tab', 'invalid', 'Unknown feed tab.');
    const nearRaw = ctx.query('near');
    const near = parseNearParam(nearRaw);
    if (nearRaw && !near) throw validation('near', 'invalid', 'near must be "lat,lng".');
    const radius = intParam(ctx.query('radius_km'), 10, 1, 50);
    const destId = ctx.query('destination_id');
    const db = ctx.db;
    const visible = [...db.posts.values()].filter((p) => db.canView(user, p));
    const browse = user.browsePath ? (db.destinationsByPath.get(user.browsePath) ?? null) : null;
    const within = (d: DestinationRecord) => visible.filter((p) => db.isWithin(p.destinationPath, d.path));

    let target: DestinationRecord | null = null;
    let source: FeedSource = 'global';
    let candidates: PostRecord[] = [];

    switch (tab) {
      case 'following':
        source = 'following';
        candidates = visible.filter((p) => db.isFollowing(user.id, p.authorId));
        break;
      case 'nearby': {
        if (!near) throw validation('near', 'required', 'The Nearby tab needs your approximate location.');
        source = 'gps';
        target = nearestCity(db, near);
        candidates = visible.filter((p) => {
          const place = p.placeId ? db.places.get(p.placeId) : undefined;
          const loc = place?.f.location ?? (p.destinationPath ? db.destinationsByPath.get(p.destinationPath)?.f.center : undefined);
          return loc !== undefined && distanceKm(near, loc) <= radius;
        });
        break;
      }
      case 'destinations':
        source = 'selected';
        target = destId ? mustDestination(db, destId, 'destination_id') : browse;
        candidates = target ? within(target) : [];
        break;
      case 'for_you':
        if (destId) {
          target = mustDestination(db, destId, 'destination_id');
          source = 'selected';
        } else if (near) {
          // The client only sends `near` after the user granted location in this browser.
          target = nearestCity(db, near);
          if (target) source = 'gps';
        }
        if (!target && browse) {
          target = browse;
          source = 'selected';
        }
        if (target) candidates = within(target);
        else if (user.travel_styles.length > 0) {
          source = 'interests';
          candidates = visible.filter((p) => p.tags.some((t) => (user.travel_styles as string[]).includes(t)));
        } else candidates = visible;
        break;
    }

    const score = (p: PostRecord) => {
      if (tab === 'following') return p.createdAt;
      const c = db.counts(p, user);
      const interest = p.tags.filter((t) => (user.travel_styles as string[]).includes(t)).length * 0.5;
      const ageDays = (ctx.now - p.createdAt) / 86_400_000;
      return Math.log1p(c.reactions + 2 * c.comments) * 1.2 + interest - ageDays;
    };
    const ranked = candidates
      .map((p) => ({ p, s: score(p) }))
      .sort((a, b) => b.s - a.s || b.p.createdAt - a.p.createdAt)
      .map(({ p }) => db.post(p, user, ctx.locale));
    const fp = `feed:${user.id}:${tab}:${destId ?? ''}:${near ? `${roundCoordinate(near.lat)},${roundCoordinate(near.lng)}` : ''}:${radius}`;
    const page = paginate(ranked, ctx, fp, 10);
    return ok({
      data: page.data,
      page: { ...page.page, reset: false },
      context: { destination: target ? db.destinationSummary(target, ctx.locale) : null, source, radius_km: tab === 'nearby' ? radius : null },
    });
  });

  // ---- posts ---------------------------------------------------------------------------------
  r.add('POST', '/v1/posts', (ctx) => {
    const { user } = ctx.auth();
    const parsed = createPostSchema.safeParse(ctx.body);
    if (!parsed.success) {
      throw problem(422, 'validation_failed', 'The post is invalid.', parsed.error.issues.map((i) => ({ field: i.path.join('.'), code: 'invalid', message: i.message })));
    }
    const input = parsed.data;
    if (input.media_ids?.length) throw notInMock('Media uploads');
    const dest = input.destination_id ? mustDestination(ctx.db, input.destination_id, 'destination_id') : null;
    const place = input.place_id ? ctx.db.places.get(input.place_id) : undefined;
    if (input.place_id && (!place || !dest || !ctx.db.isWithin(place.destinationPath, dest.path))) {
      throw validation('place_id', 'unknown', 'The place does not belong to the destination.');
    }
    const post: PostRecord = {
      id: uuidv7(ctx.now),
      authorId: user.id,
      kind: input.kind,
      body: input.body,
      language: str(ctx.body, 'language') ?? user.preferences.ui_locale,
      destinationPath: input.location_precision === 'none' ? null : (dest?.path ?? null),
      placeId: input.location_precision === 'place' ? (place?.id ?? null) : null,
      tags: input.tags ?? [],
      visibility: input.visibility,
      createdAt: ctx.now,
      editedAt: null,
      deletedAt: null,
      moderation: 'approved',
      seedReactions: {},
    };
    ctx.db.posts.set(post.id, post);
    ctx.db.comments.set(post.id, []);
    return created(ctx.db.post(post, user, ctx.locale));
  });

  r.add('GET', '/v1/posts/:postId', (ctx) => {
    const { user } = ctx.auth();
    return ok(ctx.db.post(visiblePostOr404(ctx, user), user, ctx.locale));
  });

  r.add('PATCH', '/v1/posts/:postId', (ctx) => {
    const { user } = ctx.auth();
    const post = visiblePostOr404(ctx, user);
    if (post.authorId !== user.id) throw problem(403, 'forbidden', 'Only the author can edit this post.');
    const b = ctx.body;
    if ('body' in b) {
      if (typeof b.body !== 'string' || !b.body.trim() || b.body.length > 5000) throw validation('body', 'invalid', 'Body must be 1–5000 characters.');
      post.body = b.body.trim();
    }
    oneOf(b, 'visibility', ['public', 'followers', 'connections', 'private'] as const, (v) => (post.visibility = v));
    if ('tags' in b) {
      if (!Array.isArray(b.tags) || b.tags.length > 10) throw validation('tags', 'invalid', 'Up to 10 tags.');
      post.tags = (b.tags as unknown[]).filter((t): t is string => typeof t === 'string' && t.length <= 40);
    }
    post.editedAt = ctx.now;
    return ok(ctx.db.post(post, user, ctx.locale));
  });

  r.add('DELETE', '/v1/posts/:postId', (ctx) => {
    const { user } = ctx.auth();
    const post = visiblePostOr404(ctx, user);
    if (post.authorId !== user.id) throw problem(403, 'forbidden', 'Only the author can delete this post.');
    post.deletedAt = ctx.now;
    return noContent();
  });

  r.add('POST', '/v1/posts/:postId/reactions', (ctx) => {
    const { user } = ctx.auth();
    const post = visiblePostOr404(ctx, user);
    const reaction = ctx.body.reaction as ReactionType;
    if (!(REACTION_TYPES as readonly unknown[]).includes(reaction)) throw validation('reaction', 'invalid', 'Unknown reaction.');
    const map = ctx.db.reactions.get(post.id) ?? new Map<string, ReactionType>();
    map.set(user.id, reaction);
    ctx.db.reactions.set(post.id, map);
    return ok({ reaction, counts: ctx.db.counts(post, user) });
  });

  r.add('DELETE', '/v1/posts/:postId/reactions/me', (ctx) => {
    const { user } = ctx.auth();
    ctx.db.reactions.get(visiblePostOr404(ctx, user).id)?.delete(user.id);
    return noContent();
  });

  r.add('PUT', '/v1/posts/:postId/bookmark', (ctx) => {
    const { user } = ctx.auth();
    ctx.db.bookmarks.add(`${user.id}:${visiblePostOr404(ctx, user).id}`);
    return noContent();
  });

  r.add('DELETE', '/v1/posts/:postId/bookmark', (ctx) => {
    const { user } = ctx.auth();
    ctx.db.bookmarks.delete(`${user.id}:${visiblePostOr404(ctx, user).id}`);
    return noContent();
  });

  r.add('POST', '/v1/posts/:postId/shares', (ctx) => {
    const { user } = ctx.auth();
    const post = visiblePostOr404(ctx, user);
    // Contract: only publicly listed posts (what a guest could open) get an external share link.
    if (post.visibility !== 'public' || !ctx.db.canView(null, post)) throw problem(403, 'forbidden', 'Only public posts can be shared externally.');
    ctx.db.shares.set(post.id, (ctx.db.shares.get(post.id) ?? 0) + 1);
    return created({ url: `https://travelbuddy.example/stories/${post.id}` });
  });

  r.add('GET', '/v1/posts/:postId/comments', (ctx) => {
    const { user } = ctx.auth();
    const post = visiblePostOr404(ctx, user);
    const comments = ctx.db.visibleComments(post, user).sort((a, b) => a.createdAt - b.createdAt).map((c) => ctx.db.comment(c, user));
    return ok(paginate(comments, ctx, `comments:${post.id}`, 20));
  });

  r.add('POST', '/v1/posts/:postId/comments', (ctx) => {
    const { user } = ctx.auth();
    const post = visiblePostOr404(ctx, user);
    const parsed = commentSchema.safeParse(ctx.body);
    if (!parsed.success) throw validation('body', 'invalid', 'Comments must be 1–2000 characters.');
    const comment = { id: uuidv7(ctx.now), postId: post.id, authorId: user.id, body: parsed.data.body, language: user.preferences.ui_locale, createdAt: ctx.now };
    ctx.db.comments.get(post.id)?.push(comment);
    return created(ctx.db.comment(comment, user));
  });

  // ---- relationships -------------------------------------------------------------------------
  const otherUser = (ctx: MockContext, viewer: UserRecord): UserRecord => {
    const target = ctx.db.users.get(ctx.params.userId ?? '');
    if (!target || ctx.db.blocks.has(`${target.id}:${viewer.id}`)) throw notFound();
    if (target.id === viewer.id) throw validation('user_id', 'self', 'You cannot do this to yourself.');
    return target;
  };

  r.add('PUT', '/v1/users/:userId/follow', (ctx) => {
    const { user } = ctx.auth();
    const target = otherUser(ctx, user);
    if (ctx.db.blocks.has(`${user.id}:${target.id}`)) throw problem(409, 'blocked_relationship', 'Unblock this user first.');
    ctx.db.follows.add(`${user.id}:${target.id}`);
    return ok({ status: 'following' });
  });

  r.add('DELETE', '/v1/users/:userId/follow', (ctx) => {
    const { user } = ctx.auth();
    ctx.db.follows.delete(`${user.id}:${otherUser(ctx, user).id}`);
    return noContent();
  });

  r.add('PUT', '/v1/users/:userId/block', (ctx) => {
    const { user } = ctx.auth();
    const target = otherUser(ctx, user);
    ctx.db.blocks.add(`${user.id}:${target.id}`);
    ctx.db.follows.delete(`${user.id}:${target.id}`);
    ctx.db.follows.delete(`${target.id}:${user.id}`);
    return noContent();
  });

  r.add('DELETE', '/v1/users/:userId/block', (ctx) => {
    const { user } = ctx.auth();
    ctx.db.blocks.delete(`${user.id}:${otherUser(ctx, user).id}`);
    return noContent();
  });

  // ---- trust & safety ------------------------------------------------------------------------
  r.add('POST', '/v1/reports', (ctx) => {
    const { user } = ctx.auth();
    const targetType = str(ctx.body, 'target_type');
    const targetId = str(ctx.body, 'target_id') ?? '';
    const reason = str(ctx.body, 'reason');
    if (!reason || !(REPORT_REASONS as readonly string[]).includes(reason)) throw validation('reason', 'invalid', 'Choose a reason.');
    const details = ctx.body.details;
    if (details != null && (typeof details !== 'string' || details.length > 1000)) throw validation('details', 'too_long', 'Details must be at most 1000 characters.');
    if (targetType === 'post') {
      const post = ctx.db.posts.get(targetId);
      if (!post || !ctx.db.canView(user, post)) throw notFound();
      if (ctx.body.also_block === true && post.authorId !== user.id) ctx.db.blocks.add(`${user.id}:${post.authorId}`);
    } else if (targetType === 'user') {
      if (!ctx.db.users.has(targetId)) throw notFound();
      if (ctx.body.also_block === true) ctx.db.blocks.add(`${user.id}:${targetId}`);
    } else if (targetType === 'comment') {
      if (![...ctx.db.comments.values()].some((list) => list.some((c) => c.id === targetId))) throw notFound();
    } else {
      throw validation('target_type', 'invalid', 'Unsupported target type in mock mode.');
    }
    const report = { id: uuidv7(ctx.now), reporterId: user.id, targetType, targetId, reason, createdAt: ctx.now };
    ctx.db.reports.push(report);
    return { status: 202, body: { id: report.id, status: 'open', created_at: ctx.db.iso(report.createdAt) } };
  });

  // ---- deliberately NOT simulated (web 01 §7.1 rule 5) --------------------------------------
  const unavailable: [string, string][] = [
    ['/v1/billing/*', 'Payments and subscriptions'],
    ['/v1/ai/*', 'The AI travel assistant'],
    ['/v1/media/*', 'Media uploads'],
    ['/v1/realtime/*', 'Realtime messaging'],
    ['/v1/conversations/*', 'Messaging'],
    ['/v1/messages/*', 'Messaging'],
    ['/v1/discovery/*', 'Traveler discovery'],
    ['/v1/connections/*', 'Connections'],
    ['/v1/connection-requests/*', 'Connections'],
    ['/v1/groups/*', 'Travel groups'],
    ['/v1/challenges/*', 'Group challenges'],
    ['/v1/trips/*', 'Trip planning'],
    ['/v1/places/*', 'Place search'],
    ['/v1/audio-tours/*', 'Audio tours'],
    ['/v1/notifications/*', 'Notifications'],
    ['/v1/admin/*', 'Admin analytics and moderation'],
    ['/v1/users/me/sessions/*', 'Session management'],
    ['/v1/users/me/saved-places/*', 'Saved places'],
    ['/v1/users/me/push-subscriptions/*', 'Web push'],
  ];
  for (const [pattern, feature] of unavailable) {
    r.add('*', pattern, () => {
      throw notInMock(feature);
    });
  }

  return r;
}

export { MockHttpError };
// Exported for tests that need the constant list.
export { POST_KINDS };
