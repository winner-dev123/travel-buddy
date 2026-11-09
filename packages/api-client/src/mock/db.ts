import type {
  ClientPlatform,
  Comment,
  Destination,
  DestinationSummary,
  Entitlements,
  Guide,
  GuideSummary,
  LocaleCode,
  Me,
  PlaceSummary,
  PlatformPermission,
  PlatformRole,
  Post,
  PostCounts,
  PostKind,
  PostVisibility,
  Preferences,
  PrivacySettings,
  PublicPost,
  ReactionType,
  TravelStyle,
  UserSummary,
} from '@travelbuddy/domain-types';
import { DESTINATIONS, PLACES, type DestinationFixture, type Loc, type PlaceFixture } from './fixtures/destinations';
import { FOLLOWS, PERSONAS, POSTS } from './fixtures/social';
import { fixtureId } from './ids';

export const ACCESS_TTL_MS = 15 * 60 * 1000;
export const REFRESH_TTL_MS = 30 * 24 * 60 * 60 * 1000;
/** ADR-0011: a just-rotated refresh token may be replayed for 30 s and yields the same successor. */
export const REFRESH_REUSE_LEEWAY_MS = 30_000;
export const DEV_TOKEN_TTL_MS = 10 * 60 * 1000;
const CONTENT_UPDATED_AT = '2026-10-01T00:00:00Z';

export interface DestinationRecord {
  id: string;
  path: string;
  slug: string;
  parentPath: string | null;
  f: DestinationFixture;
}

export interface PlaceRecord {
  id: string;
  destinationPath: string;
  f: PlaceFixture;
}

export interface UserRecord {
  id: string;
  identitySub: string;
  handle: string;
  email: string;
  display_name: string;
  bio: string | null;
  travel_styles: TravelStyle[];
  home_country_code: string | null;
  languages: string[];
  created_at: number;
  updated_at: number;
  roles: PlatformRole[];
  status: 'active' | 'suspended' | 'pending_deletion';
  onboarding_completed: boolean;
  preferences: Preferences;
  privacy: PrivacySettings;
  browsePath: string | null;
  premium: boolean;
  birth_year: number | null;
}

export interface TokenPair {
  access: string;
  accessExpiresAt: number;
  refresh: string;
  refreshExpiresAt: number;
}

export interface SessionRecord {
  id: string;
  userId: string;
  client: ClientPlatform;
  createdAt: number;
  lastSeenAt: number;
  current: TokenPair;
  previous: { refresh: string; rotatedAt: number; successor: TokenPair } | null;
  revoked: boolean;
}

export interface PostRecord {
  id: string;
  authorId: string;
  kind: PostKind;
  body: string;
  language: string;
  destinationPath: string | null;
  placeId: string | null;
  tags: string[];
  visibility: PostVisibility;
  createdAt: number;
  editedAt: number | null;
  deletedAt: number | null;
  moderation: 'approved' | 'removed';
  seedReactions: Partial<Record<ReactionType, number>>;
}

export interface CommentRecord {
  id: string;
  postId: string;
  authorId: string;
  body: string;
  language: string;
  createdAt: number;
}

export interface DevIdentity {
  sub: string;
  email: string;
  email_verified: boolean;
  name: string | null;
  expiresAt: number;
}

const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

export function defaultPrivacy(): PrivacySettings {
  // Privacy by default: discovery off, no consents recorded (brief §8, §15).
  return {
    discovery_enabled: false,
    discovery_granularity: 'city',
    connection_requests_from: 'everyone',
    profile_visibility: 'public',
    show_trips_on_profile: false,
    read_receipts_enabled: true,
    post_location_default: 'destination',
    // PROF-008: opt-in only. Public stories are noindex unless the author enables this.
    search_engine_indexing: false,
    location_consent: null,
    discovery_consent: null,
  };
}

export function defaultPreferences(locale: LocaleCode): Preferences {
  return {
    ui_locale: locale,
    content_languages: [locale],
    time_zone: 'UTC',
    currency_code: 'USD',
    distance_unit: 'km',
    auto_translate: false,
    notification_settings: {},
  };
}

/** Doc 07 §3 values (configuration in the real backend). */
function entitlementsFor(user: UserRecord, now: number): Entitlements {
  const premium = user.premium;
  return {
    plan: premium ? 'premium' : 'free',
    status: premium ? 'active' : 'none',
    premium_until: premium ? iso(now + 30 * 24 * 3600 * 1000) : null,
    store_grace_until: null,
    features: {
      'groups.create': premium,
      'challenges.create': premium,
      'guides.premium': premium,
      'audio_tours.premium': premium,
      'ai.trip_replan': premium,
    },
    quotas: {
      'ai.itinerary_generations': { limit: premium ? 60 : 5, used: 0, resets_at: null },
      'ai.trip_replans': { limit: premium ? 60 : 0, used: 0, resets_at: null },
      'offline.packages': { limit: premium ? 15 : 1, used: 0, resets_at: null },
      'groups.owned': { limit: premium ? 10 : 0, used: 0, resets_at: null },
    },
    active_subscription: null,
  };
}

/** Cumulative role ladder from the contract's PlatformPermission enum (backend is authoritative). */
const SUPPORT: PlatformPermission[] = ['users.read', 'moderation.reports.read', 'moderation.actions.read'];
const MODERATOR: PlatformPermission[] = [...SUPPORT, 'moderation.reports.manage', 'moderation.actions.write', 'users.suspend', 'content.rewards.review'];
const ADMIN: PlatformPermission[] = [...MODERATOR, 'users.read_sensitive', 'users.ban', 'content.destinations.write', 'content.feature', 'entitlements.grant', 'audit.read'];
const SUPERADMIN: PlatformPermission[] = [...ADMIN, 'billing.configure', 'roles.assign'];
const LADDER: Record<PlatformRole, PlatformPermission[]> = { support: SUPPORT, moderator: MODERATOR, admin: ADMIN, superadmin: SUPERADMIN };

export function permissionsFor(roles: readonly PlatformRole[]): PlatformPermission[] {
  return [...new Set(roles.flatMap((r) => LADDER[r]))];
}

export class MockDb {
  readonly destinations = new Map<string, DestinationRecord>();
  readonly destinationsByPath = new Map<string, DestinationRecord>();
  readonly places = new Map<string, PlaceRecord>();
  readonly placesBySlug = new Map<string, PlaceRecord>();
  readonly users = new Map<string, UserRecord>();
  readonly usersBySub = new Map<string, string>();
  readonly sessions = new Map<string, SessionRecord>();
  readonly accessTokens = new Map<string, { sessionId: string; expiresAt: number }>();
  readonly posts = new Map<string, PostRecord>();
  readonly comments = new Map<string, CommentRecord[]>();
  readonly reactions = new Map<string, Map<string, ReactionType>>();
  readonly bookmarks = new Set<string>();
  readonly follows = new Set<string>();
  readonly blocks = new Set<string>();
  readonly reports: { id: string; reporterId: string; targetType: string; targetId: string; reason: string; createdAt: number }[] = [];
  readonly idempotency = new Map<string, { fingerprint: string; status: number; body: unknown }>();
  readonly devIdentities = new Map<string, DevIdentity>();

  constructor(
    readonly now: () => number,
    /** HMAC key for self-describing mock tokens (see tokens.ts). */
    readonly tokenSecret = 'travelbuddy-mock-token-key-development-only',
  ) {
    this.seed();
  }

  // ---- Seed ---------------------------------------------------------------------------------

  private seed(): void {
    const now = this.now();
    for (const f of DESTINATIONS) {
      const parts = f.path.split('/');
      const rec: DestinationRecord = {
        id: fixtureId(`destination:${f.path}`),
        path: f.path,
        slug: parts[parts.length - 1] as string,
        parentPath: parts.length > 1 ? parts.slice(0, -1).join('/') : null,
        f,
      };
      this.destinations.set(rec.id, rec);
      this.destinationsByPath.set(rec.path, rec);
    }
    for (const f of PLACES) {
      const rec: PlaceRecord = { id: fixtureId(`place:${f.slug}`), destinationPath: f.destination, f };
      this.places.set(rec.id, rec);
      this.placesBySlug.set(f.slug, rec);
    }
    PERSONAS.forEach((p, i) => {
      const created = now - (400 - i * 20) * 24 * 3600 * 1000;
      const user: UserRecord = {
        id: fixtureId(`user:${p.handle}`),
        identitySub: `persona:${p.handle}`,
        handle: p.handle,
        email: p.email,
        display_name: p.display_name,
        bio: p.bio,
        travel_styles: [...p.travel_styles],
        home_country_code: p.home_country_code,
        languages: [...p.languages],
        created_at: created,
        updated_at: created,
        roles: p.roles ? [...p.roles] : [],
        status: 'active',
        onboarding_completed: true,
        preferences: defaultPreferences(p.preferred_language),
        privacy: { ...defaultPrivacy(), search_engine_indexing: p.indexing ?? false },
        browsePath: p.browse ?? null,
        premium: p.premium ?? false,
        birth_year: 1990,
      };
      this.users.set(user.id, user);
      this.usersBySub.set(user.identitySub, user.id);
    });
    for (const [a, b] of FOLLOWS) this.follows.add(`${this.userIdByHandle(a)}:${this.userIdByHandle(b)}`);
    for (const p of POSTS) {
      const id = fixtureId(`post:${p.key}`);
      this.posts.set(id, {
        id,
        authorId: this.userIdByHandle(p.author),
        kind: p.kind ?? 'experience',
        body: p.caption,
        language: p.language,
        destinationPath: p.destination,
        placeId: p.place ? (this.placesBySlug.get(p.place)?.id ?? null) : null,
        tags: [...p.tags],
        visibility: p.visibility,
        createdAt: now - p.hours_ago * 3600 * 1000,
        editedAt: null,
        deletedAt: null,
        moderation: 'approved',
        seedReactions: { ...p.reactions },
      });
      this.comments.set(
        id,
        (p.comments ?? []).map((c, i) => ({
          id: fixtureId(`comment:${p.key}:${i}`),
          postId: id,
          authorId: this.userIdByHandle(c.author),
          body: c.body,
          language: 'en',
          createdAt: now - c.hours_ago * 3600 * 1000,
        })),
      );
    }
  }

  userIdByHandle(handle: string): string {
    return fixtureId(`user:${handle}`);
  }

  findUserByHandle(handle: string): UserRecord | undefined {
    for (const u of this.users.values()) if (u.handle === handle) return u;
    return undefined;
  }

  // ---- Relationships -------------------------------------------------------------------------

  isBlockedEitherWay(a: string, b: string): boolean {
    return this.blocks.has(`${a}:${b}`) || this.blocks.has(`${b}:${a}`);
  }

  isFollowing(follower: string, followee: string): boolean {
    return this.follows.has(`${follower}:${followee}`);
  }

  /** `social.can_view` (doc 02 §9) as the mock understands it. */
  canView(viewer: UserRecord | null, post: PostRecord): boolean {
    if (post.deletedAt !== null || post.moderation !== 'approved') return false;
    if (viewer && this.isBlockedEitherWay(viewer.id, post.authorId)) return false;
    if (viewer && viewer.id === post.authorId) return true;
    switch (post.visibility) {
      case 'public':
        return true;
      case 'followers':
        return viewer !== null && this.isFollowing(viewer.id, post.authorId);
      case 'connections':
      case 'private':
        return false;
    }
  }

  isWithin(path: string | null, ancestorPath: string): boolean {
    return path !== null && (path === ancestorPath || path.startsWith(`${ancestorPath}/`));
  }

  // ---- Destinations --------------------------------------------------------------------------

  loc(value: Loc | undefined, locale: LocaleCode): string | null {
    if (!value) return null;
    return value[locale] ?? value.en;
  }

  countryOf(rec: DestinationRecord): DestinationRecord | undefined {
    return this.destinationsByPath.get(rec.path.split('/')[0] as string);
  }

  childrenOf(rec: DestinationRecord): DestinationRecord[] {
    return [...this.destinations.values()].filter((d) => d.parentPath === rec.path);
  }

  /** Popularity proxy used for `sort=popularity`: public stories in the subtree. */
  popularity(rec: DestinationRecord): number {
    let n = 0;
    for (const p of this.posts.values()) {
      if (p.visibility === 'public' && this.canView(null, p) && this.isWithin(p.destinationPath, rec.path)) n++;
    }
    return n;
  }

  private centroid(rec: DestinationRecord): { lat: number; lng: number } {
    if (rec.f.center) return { ...rec.f.center };
    const kids = this.childrenOf(rec).filter((k) => k.f.center);
    if (kids.length === 0) return { lat: 0, lng: 0 };
    return {
      lat: kids.reduce((s, k) => s + (k.f.center?.lat ?? 0), 0) / kids.length,
      lng: kids.reduce((s, k) => s + (k.f.center?.lng ?? 0), 0) / kids.length,
    };
  }

  destinationSummary(rec: DestinationRecord, locale: LocaleCode): DestinationSummary {
    const country = this.countryOf(rec);
    return {
      id: rec.id,
      kind: rec.f.kind,
      slug: rec.slug,
      path: rec.path,
      name: this.loc(rec.f.name, locale) ?? rec.slug,
      country_code: rec.f.country_code,
      country_name: rec.f.kind === 'country' || !country ? null : this.loc(country.f.name, locale),
      continent: rec.f.continent,
      tagline: this.loc(rec.f.tagline, locale),
      cover: null,
    };
  }

  destinationDetail(rec: DestinationRecord, locale: LocaleCode): Destination {
    const ancestors: DestinationSummary[] = [];
    let parent = rec.parentPath;
    while (parent) {
      const p = this.destinationsByPath.get(parent);
      if (!p) break;
      ancestors.unshift(this.destinationSummary(p, locale));
      parent = p.parentPath;
    }
    const firstChildTz = this.childrenOf(rec).find((k) => k.f.time_zone)?.f.time_zone;
    return {
      ...this.destinationSummary(rec, locale),
      parent_id: rec.parentPath ? (this.destinationsByPath.get(rec.parentPath)?.id ?? null) : null,
      ancestors,
      centroid: this.centroid(rec),
      time_zone: rec.f.time_zone ?? firstChildTz ?? 'UTC',
      is_featured: rec.f.featured ?? false,
      has_children: this.childrenOf(rec).length > 0,
      has_guides: Boolean(rec.f.overview),
    };
  }

  // ---- Guides (one free editorial guide per destination with an overview) --------------------

  guideId(rec: DestinationRecord): string {
    return fixtureId(`guide:${rec.path}`);
  }

  guideRecordById(id: string): DestinationRecord | undefined {
    for (const d of this.destinations.values()) if (d.f.overview && this.guideId(d) === id) return d;
    return undefined;
  }

  guideSummary(rec: DestinationRecord, locale: LocaleCode): GuideSummary {
    return {
      id: this.guideId(rec),
      destination_id: rec.id,
      locale: 'en',
      title: `${this.loc(rec.f.name, 'en')}: the essentials`,
      summary: this.loc(rec.f.tagline, locale) ?? (rec.f.overview ?? '').split('. ')[0] ?? '',
      tier: 'free',
      entitled: true,
      product_id: null,
      version: 1,
      published_at: CONTENT_UPDATED_AT,
    };
  }

  guide(rec: DestinationRecord, locale: LocaleCode): Guide {
    const f = rec.f;
    const placeIds = [...this.places.values()].filter((p) => this.isWithin(p.destinationPath, rec.path)).map((p) => p.id);
    const sections: Guide['sections'] = [{ id: 'overview', kind: 'prose', heading: 'Overview', body_markdown: f.overview ?? '', place_ids: [] }];
    if (f.highlights?.length) {
      sections.push({ id: 'highlights', kind: 'prose', heading: 'Highlights', body_markdown: f.highlights.map((h) => `- ${h}`).join('\n'), place_ids: placeIds });
    }
    if (f.best_time) sections.push({ id: 'when-to-go', kind: 'prose', heading: 'When to go', body_markdown: f.best_time, place_ids: [] });
    if (f.faqs?.length) {
      sections.push({
        id: 'faq',
        kind: 'faq',
        heading: 'Frequently asked questions',
        body_markdown: '',
        place_ids: [],
        faq_items: f.faqs.map((q) => ({ question: q.question, answer_markdown: q.answer })),
      });
    }
    const summary = this.guideSummary(rec, locale);
    return {
      id: summary.id,
      destination: this.destinationSummary(rec, locale),
      locale: 'en',
      title: summary.title,
      summary: summary.summary,
      sections,
      tier: 'free',
      version: 1,
      content_license: 'Travel Buddy editorial (development fixture)',
      attribution: null,
      published_at: CONTENT_UPDATED_AT,
      updated_at: CONTENT_UPDATED_AT,
    };
  }

  placeSummary(rec: PlaceRecord): PlaceSummary {
    return {
      id: rec.id,
      name: rec.f.name,
      category: rec.f.category,
      destination_id: this.destinationsByPath.get(rec.destinationPath)?.id ?? '',
      location: { ...rec.f.location },
    };
  }

  // ---- Social --------------------------------------------------------------------------------

  userSummary(userId: string): UserSummary {
    const u = this.users.get(userId);
    return { id: userId, handle: u?.handle ?? 'deleted', display_name: u?.display_name ?? 'Deleted user', avatar: null };
  }

  visibleComments(post: PostRecord, viewer: UserRecord | null): CommentRecord[] {
    return (this.comments.get(post.id) ?? []).filter((c) => !viewer || !this.isBlockedEitherWay(viewer.id, c.authorId));
  }

  counts(post: PostRecord, viewer: UserRecord | null): PostCounts {
    const byType: Record<ReactionType, number> = { like: 0, love: 0, helpful: 0, wow: 0, ...post.seedReactions };
    for (const kind of this.reactions.get(post.id)?.values() ?? []) byType[kind] += 1;
    let bookmarks = 0;
    for (const b of this.bookmarks) if (b.endsWith(`:${post.id}`)) bookmarks++;
    return {
      reactions: byType.like + byType.love + byType.helpful + byType.wow,
      comments: this.visibleComments(post, viewer).length,
      bookmarks,
      shares: 0,
      reactions_by_type: byType,
    };
  }

  publicPost(post: PostRecord, locale: LocaleCode, viewer: UserRecord | null = null): PublicPost {
    const dest = post.destinationPath ? this.destinationsByPath.get(post.destinationPath) : undefined;
    const place = post.placeId ? this.places.get(post.placeId) : undefined;
    return {
      id: post.id,
      author: this.userSummary(post.authorId),
      kind: post.kind,
      body: post.body,
      language: post.language,
      visibility: post.visibility,
      location_precision: place ? 'place' : dest ? 'destination' : 'none',
      primary_destination: dest ? this.destinationSummary(dest, locale) : null,
      place: place ? this.placeSummary(place) : null,
      travel_date: null,
      rating: null,
      tags: [...post.tags],
      media: [],
      published_at: iso(post.createdAt),
      edited_at: post.editedAt ? iso(post.editedAt) : null,
      counts: this.counts(post, viewer),
      indexable: post.visibility === 'public' && post.moderation === 'approved' && this.users.get(post.authorId)?.privacy.search_engine_indexing === true,
    };
  }

  post(post: PostRecord, viewer: UserRecord, locale: LocaleCode): Post {
    const own = post.authorId === viewer.id;
    return {
      ...this.publicPost(post, locale, viewer),
      viewer: {
        reaction: this.reactions.get(post.id)?.get(viewer.id) ?? null,
        bookmarked: this.bookmarks.has(`${viewer.id}:${post.id}`),
        is_author: own,
        can_edit: own,
        can_delete: own,
        can_comment: true,
      },
      moderation_state: post.moderation,
    };
  }

  comment(c: CommentRecord, viewer: UserRecord | null): Comment {
    const own = viewer?.id === c.authorId;
    return {
      id: c.id,
      post_id: c.postId,
      parent_comment_id: null,
      author: this.userSummary(c.authorId),
      body: c.body,
      language: c.language,
      reply_count: 0,
      deleted: false,
      created_at: iso(c.createdAt),
      edited_at: null,
      viewer: { can_edit: own, can_delete: own },
    };
  }

  // ---- Me ------------------------------------------------------------------------------------

  me(u: UserRecord, locale: LocaleCode): Me {
    const browse = u.browsePath ? this.destinationsByPath.get(u.browsePath) : undefined;
    let posts = 0;
    for (const p of this.posts.values()) if (p.authorId === u.id && p.deletedAt === null) posts++;
    let followers = 0;
    let following = 0;
    for (const f of this.follows) {
      if (f.endsWith(`:${u.id}`)) followers++;
      if (f.startsWith(`${u.id}:`)) following++;
    }
    return {
      account: {
        id: u.id,
        email: u.email,
        email_verified: true,
        status: u.status === 'pending_deletion' ? 'pending_deletion' : 'active',
        primary_locale: u.preferences.ui_locale,
        age_assured: true,
        deletion_scheduled_for: null,
        created_at: iso(u.created_at),
        restrictions: [],
      },
      profile: {
        id: u.id,
        handle: u.handle,
        display_name: u.display_name,
        bio: u.bio,
        avatar: null,
        home_country_code: u.home_country_code,
        home_region: null,
        travel_styles: [...u.travel_styles],
        interests: [],
        languages_spoken: [...u.languages],
        account_visibility: 'public',
        counts: { posts, followers, following },
        updated_at: iso(u.updated_at),
      },
      preferences: { ...u.preferences },
      privacy: { ...u.privacy },
      roles: [...u.roles],
      permissions: permissionsFor(u.roles),
      onboarding_completed: u.onboarding_completed,
      browse_destination: browse ? this.destinationSummary(browse, locale) : null,
      entitlements: entitlementsFor(u, this.now()),
    };
  }

  iso = iso;
}
