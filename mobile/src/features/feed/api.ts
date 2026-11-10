import type { ApiClient } from '@/api';

import type {
  Comment,
  DestinationSummary,
  FeedPage,
  FeedTab,
  Page,
  Post,
  PostKind,
  ReactionType,
} from './types';

export const feedKeys = {
  all: ['feed'] as const,
  list: (tab: FeedTab | 'guest', ...rest: (string | null | undefined)[]) =>
    ['feed', tab, ...rest] as const,
  post: (id: string) => ['post', id] as const,
  comments: (id: string) => ['post', id, 'comments'] as const,
};

export interface FeedOptions {
  /** Coarse device position (`lat,lng`) for the Nearby tab. */
  near?: string;
  radiusKm?: number;
  categories?: PostKind[];
}

/** `GET /v1/feed` (signed in) — the server explains its fallback choice in `context`. */
export function fetchFeed(
  client: ApiClient,
  tab: FeedTab,
  cursor?: string,
  options: FeedOptions = {},
): Promise<FeedPage> {
  return client.get<FeedPage>('/v1/feed', {
    query: {
      tab,
      cursor,
      limit: 20,
      ...(options.near ? { near: options.near, radius_km: options.radiusKm ?? 10 } : {}),
      ...(options.categories?.length ? { category: options.categories } : {}),
    },
  });
}

/** `GET /v1/public/posts` — guest mode (public stories only, capped at three pages). */
export function fetchPublicPosts(client: ApiClient, cursor?: string): Promise<FeedPage> {
  return client.get<FeedPage>('/v1/public/posts', { query: { cursor, limit: 20 } });
}

export function fetchPost(client: ApiClient, id: string, signedIn: boolean): Promise<Post> {
  return client.get<Post>(signedIn ? `/v1/posts/${id}` : `/v1/public/posts/${id}`);
}

export function fetchComments(client: ApiClient, postId: string): Promise<Page<Comment>> {
  return client.get<Page<Comment>>(`/v1/posts/${postId}/comments`, { query: { limit: 50 } });
}

export function createComment(
  client: ApiClient,
  postId: string,
  body: string,
  idempotencyKey: string,
): Promise<Comment> {
  return client.post<Comment>(`/v1/posts/${postId}/comments`, { body: { body }, idempotencyKey });
}

export function setReaction(
  client: ApiClient,
  postId: string,
  reaction: ReactionType | null,
): Promise<unknown> {
  return reaction === null
    ? client.delete(`/v1/posts/${postId}/reactions/me`)
    : client.post(`/v1/posts/${postId}/reactions`, { body: { reaction } });
}

export interface NewPost {
  kind: PostKind;
  body: string;
  visibility: 'public' | 'followers' | 'private';
  destination: DestinationSummary | null;
  /** Uploaded media (`MediaAsset` ids), in display order. */
  mediaIds?: string[];
}

export function createPost(
  client: ApiClient,
  post: NewPost,
  idempotencyKey: string,
): Promise<Post> {
  return client.post<Post>('/v1/posts', {
    idempotencyKey,
    body: {
      kind: post.kind,
      body: post.body,
      visibility: post.visibility,
      location_precision: post.destination ? 'destination' : 'none',
      ...(post.destination ? { destination_id: post.destination.id } : {}),
      ...(post.mediaIds?.length ? { media_ids: post.mediaIds } : {}),
    },
  });
}

export async function searchDestinations(
  client: ApiClient,
  q: string,
): Promise<DestinationSummary[]> {
  const page = await client.get<Page<DestinationSummary>>('/v1/destinations/search', {
    query: { q, limit: 8 },
  });
  return page.data;
}

/** Contract `Translation`: always machine-made, never replaces the original (POST-010). */
export interface PostTranslation {
  post_id: string;
  source_language: string;
  target_language: string;
  text: string;
  machine_translated: true;
  provider_attribution?: string | null;
}

/** Version of the post-translation consent text (I18N-006). */
export const TRANSLATION_CONSENT_VERSION = '2026-11-01';

export function translatePost(
  client: ApiClient,
  postId: string,
  target: string,
): Promise<PostTranslation> {
  return client.get<PostTranslation>(`/v1/posts/${postId}/translation`, { query: { target } });
}

export async function allowTranslation(client: ApiClient): Promise<void> {
  await client.post('/v1/users/me/consents', {
    body: {
      consent_type: 'post_translation',
      version: TRANSLATION_CONSENT_VERSION,
      granted: true,
      source: 'prompt',
    },
  });
}
