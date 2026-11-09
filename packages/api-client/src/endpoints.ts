import type {
  AuthResult,
  BrowseDestination,
  ClientConfig,
  Comment,
  CreateCommentRequest,
  CreatePostRequest,
  CreateReportRequest,
  CursorQuery,
  Destination,
  DestinationListQuery,
  DestinationSummary,
  DevIdpToken,
  DevIdpTokenRequest,
  Entitlements,
  FeedPage,
  FeedTab,
  Guide,
  GuideSummary,
  LoginRequest,
  LogoutRequest,
  Me,
  Page,
  Post,
  PostKind,
  Preferences,
  PrivacySettings,
  PublicPost,
  ReactionResult,
  ReactionType,
  RealtimeTicket,
  RefreshRequest,
  RegisterRequest,
  ReportReceipt,
  SessionTokens,
  ShareLink,
  UpdateMyProfileRequest,
  UpdatePostRequest,
  UpdatePreferencesRequest,
  UpdatePrivacySettingsRequest,
  UserSummary,
  UUID,
} from '@travelbuddy/domain-types';
import { newIdempotencyKey, type ApiClient } from './core/client';

export type FeedFeedbackKind = 'hide' | 'not_interested' | 'see_less_author';
import type { CacheHint } from './core/types';

const enc = encodeURIComponent;

export interface FeedQuery extends CursorQuery {
  tab: FeedTab;
  destination_id?: UUID | null;
  /** `lat,lng` rounded to 3 decimals. Request-scoped only (doc 02 §6). */
  near?: string | null;
  radius_km?: number | null;
  sort?: 'ranked' | 'recent' | 'popular';
}

/**
 * Typed bindings for the `/v1` endpoints the web consumes. Shapes come from the generated contract
 * (contracts/openapi/openapi.yaml). Usage: `createApi(client).destinations.lookup('brazil/rio-de-janeiro')`.
 */
export function createApi(c: ApiClient) {
  return {
    auth: {
      login: (body: LoginRequest) =>
        c.request<AuthResult>({ method: 'POST', path: '/v1/auth/login', body, cache: 'no-store' }),
      register: (body: RegisterRequest) =>
        c.request<AuthResult>({
          method: 'POST',
          path: '/v1/auth/register',
          body,
          cache: 'no-store',
          idempotencyKey: newIdempotencyKey(),
        }),
      refresh: (body: RefreshRequest) =>
        c.request<SessionTokens>({ method: 'POST', path: '/v1/auth/refresh', body, cache: 'no-store' }),
      /** Bearer-authenticated; revokes the current session (or all sessions). */
      logout: (body: LogoutRequest = {}) =>
        c.request<void>({ method: 'POST', path: '/v1/auth/logout', body, cache: 'no-store' }),
      /** Development/test environments only (404 elsewhere). */
      devIdpToken: (body: DevIdpTokenRequest) =>
        c.request<DevIdpToken>({ method: 'POST', path: '/v1/dev/idp/token', body, cache: 'no-store' }),
    },

    config: {
      /** Global client configuration: legal versions, feature flags, VAPID key (contract ClientConfig). */
      get: (params: { platform: 'web' | 'ios' | 'android'; app_version: string }, cache?: CacheHint) =>
        c.request<ClientConfig>({ method: 'GET', path: '/v1/client-config', query: { ...params }, cache }),
    },

    me: {
      get: () => c.request<Me>({ method: 'GET', path: '/v1/users/me', cache: 'no-store' }),
      update: (body: UpdateMyProfileRequest) => c.request<Me>({ method: 'PATCH', path: '/v1/users/me', body }),
      updatePreferences: (body: UpdatePreferencesRequest) =>
        c.request<Preferences>({ method: 'PATCH', path: '/v1/users/me/preferences', body }),
      updatePrivacy: (body: UpdatePrivacySettingsRequest) =>
        c.request<PrivacySettings>({ method: 'PATCH', path: '/v1/users/me/privacy', body }),
      setBrowseDestination: (destinationId: UUID) =>
        c.request<BrowseDestination>({
          method: 'PUT',
          path: '/v1/users/me/browse-destination',
          body: { destination_id: destinationId },
        }),
      clearBrowseDestination: () => c.request<void>({ method: 'DELETE', path: '/v1/users/me/browse-destination' }),
      completeOnboarding: () => c.request<Me>({ method: 'POST', path: '/v1/users/me/onboarding/complete' }),
      bookmarks: (query: CursorQuery = {}) =>
        c.request<Page<Post>>({ method: 'GET', path: '/v1/users/me/bookmarks', query: { ...query } }),
    },

    destinations: {
      /** Anonymous-capable list. Use `sort: 'slug'` for stable sitemap enumeration. */
      list: (query: DestinationListQuery = {}, cache?: CacheHint) =>
        c.request<Page<DestinationSummary>>({
          method: 'GET',
          path: '/v1/destinations',
          query: { ...query, kind: query.kind?.join(',') },
          cache,
        }),
      featured: (query: CursorQuery = {}, cache?: CacheHint) =>
        c.request<Page<DestinationSummary>>({ method: 'GET', path: '/v1/destinations/featured', query: { ...query }, cache }),
      search: (q: string, options: { kind?: string[]; country?: string; limit?: number } = {}) =>
        c.request<Page<DestinationSummary>>({
          method: 'GET',
          path: '/v1/destinations/search',
          query: { q, kind: options.kind?.join(','), country: options.country, limit: options.limit ?? 8 },
        }),
      lookup: (path: string, cache?: CacheHint) =>
        c.request<Destination>({ method: 'GET', path: '/v1/destinations/lookup', query: { path }, cache }),
      get: (id: UUID, cache?: CacheHint) =>
        c.request<Destination>({ method: 'GET', path: `/v1/destinations/${enc(id)}`, cache }),
      children: (id: UUID, query: CursorQuery = {}, cache?: CacheHint) =>
        c.request<Page<DestinationSummary>>({
          method: 'GET',
          path: `/v1/destinations/${enc(id)}/children`,
          query: { ...query },
          cache,
        }),
      /** Resolves the (rounded) device point to a destination; the server discards the point. */
      resolve: (near: string) =>
        c.request<Destination>({ method: 'GET', path: '/v1/destinations/resolve', query: { near }, cache: 'no-store' }),
      guides: (id: UUID, cache?: CacheHint) =>
        c.request<{ data: GuideSummary[] }>({ method: 'GET', path: `/v1/destinations/${enc(id)}/guides`, cache }),
    },

    guides: {
      get: (id: UUID, cache?: CacheHint) => c.request<Guide>({ method: 'GET', path: `/v1/guides/${enc(id)}`, cache }),
    },

    publicPosts: {
      list: (query: CursorQuery & { destination_id?: UUID; category?: PostKind[] } = {}, cache?: CacheHint) =>
        c.request<Page<PublicPost>>({ method: 'GET', path: '/v1/public/posts', query: { ...query }, cache }),
      get: (id: UUID, cache?: CacheHint) =>
        c.request<PublicPost>({ method: 'GET', path: `/v1/public/posts/${enc(id)}`, cache }),
    },

    feed: {
      get: (query: FeedQuery, signal?: AbortSignal) =>
        c.request<FeedPage>({ method: 'GET', path: '/v1/feed', query: { ...query }, signal, cache: 'no-store' }),
      /** FEED-007: hide a post, mark it not interesting, or see less from its author. Idempotent (204). */
      feedback: (postId: UUID, kind: FeedFeedbackKind) =>
        c.request<void>({ method: 'POST', path: '/v1/feed/feedback', body: { post_id: postId, kind } }),
    },

    posts: {
      create: (body: CreatePostRequest, idempotencyKey: string = newIdempotencyKey()) =>
        c.request<Post>({ method: 'POST', path: '/v1/posts', body, idempotencyKey }),
      get: (id: UUID) => c.request<Post>({ method: 'GET', path: `/v1/posts/${enc(id)}` }),
      update: (id: UUID, body: UpdatePostRequest) =>
        c.request<Post>({ method: 'PATCH', path: `/v1/posts/${enc(id)}`, body }),
      remove: (id: UUID) => c.request<void>({ method: 'DELETE', path: `/v1/posts/${enc(id)}` }),
      /** Idempotent upsert: one reaction per user per post. */
      react: (id: UUID, reaction: ReactionType) =>
        c.request<ReactionResult>({ method: 'POST', path: `/v1/posts/${enc(id)}/reactions`, body: { reaction } }),
      unreact: (id: UUID) => c.request<void>({ method: 'DELETE', path: `/v1/posts/${enc(id)}/reactions/me` }),
      bookmark: (id: UUID) => c.request<void>({ method: 'PUT', path: `/v1/posts/${enc(id)}/bookmark` }),
      unbookmark: (id: UUID) => c.request<void>({ method: 'DELETE', path: `/v1/posts/${enc(id)}/bookmark` }),
      share: (id: UUID) => c.request<ShareLink>({ method: 'POST', path: `/v1/posts/${enc(id)}/shares` }),
      comments: (id: UUID, query: CursorQuery = {}) =>
        c.request<Page<Comment>>({ method: 'GET', path: `/v1/posts/${enc(id)}/comments`, query: { ...query } }),
      addComment: (id: UUID, body: CreateCommentRequest, idempotencyKey: string = newIdempotencyKey()) =>
        c.request<Comment>({ method: 'POST', path: `/v1/posts/${enc(id)}/comments`, body, idempotencyKey }),
    },

    users: {
      follow: (userId: UUID) => c.request<unknown>({ method: 'PUT', path: `/v1/users/${enc(userId)}/follow` }),
      unfollow: (userId: UUID) => c.request<void>({ method: 'DELETE', path: `/v1/users/${enc(userId)}/follow` }),
      block: (userId: UUID) => c.request<void>({ method: 'PUT', path: `/v1/users/${enc(userId)}/block` }),
      unblock: (userId: UUID) => c.request<void>({ method: 'DELETE', path: `/v1/users/${enc(userId)}/block` }),
      /** Accounts the signed-in user has blocked (privacy centre, SAFE-001). */
      blocks: (query: CursorQuery = {}) => c.request<Page<UserSummary>>({ method: 'GET', path: '/v1/users/me/blocks', query: { ...query } }),
    },

    reports: {
      create: (body: CreateReportRequest) =>
        c.request<ReportReceipt>({ method: 'POST', path: '/v1/reports', body, idempotencyKey: newIdempotencyKey() }),
    },

    billing: {
      products: () =>
        c.request<{ data: unknown[] }>({ method: 'GET', path: '/v1/billing/products', query: { platform: 'web' } }),
      entitlements: () =>
        c.request<Entitlements>({ method: 'GET', path: '/v1/billing/entitlements', cache: 'no-store' }),
      checkout: (body: { product_id: UUID; success_path: string; cancel_path: string }) =>
        c.request<{ url: string }>({
          method: 'POST',
          path: '/v1/billing/checkout-sessions',
          body,
          idempotencyKey: newIdempotencyKey(),
        }),
      portal: () => c.request<{ url: string }>({ method: 'POST', path: '/v1/billing/portal-sessions' }),
    },

    realtime: {
      ticket: () => c.request<RealtimeTicket>({ method: 'POST', path: '/v1/realtime/tickets', cache: 'no-store' }),
    },
  };
}

export type Api = ReturnType<typeof createApi>;
