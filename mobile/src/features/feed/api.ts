import type { ApiClient } from '@/api';
import { fixParams, type DeviceFix } from '@/features/feed/location';

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
  replies: (commentId: string) => ['comment', commentId, 'replies'] as const,
  bookmarks: ['me', 'bookmarks'] as const,
};

export interface FeedOptions {
  /** Coarse device position (`lat,lng`) for the Nearby tab. */
  near?: string;
  /** When and how precisely it was taken (LOC-007, LOC-008). */
  fix?: DeviceFix;
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
      ...(options.near
        ? { near: options.near, radius_km: options.radiusKm ?? 10, ...fixParams(options.fix) }
        : {}),
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
  parentId?: string,
): Promise<Comment> {
  return client.post<Comment>(`/v1/posts/${postId}/comments`, {
    body: { body, ...(parentId ? { parent_comment_id: parentId } : {}) },
    idempotencyKey,
  });
}

/** Replies to a top-level comment (one level only, POST-005), oldest first. */
export function fetchReplies(client: ApiClient, commentId: string): Promise<Page<Comment>> {
  return client.get<Page<Comment>>(`/v1/comments/${commentId}/replies`, { query: { limit: 50 } });
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

/** `DELETE /v1/comments/{id}`: its author, or the author of the story it's on. */
export function deleteComment(client: ApiClient, commentId: string): Promise<void> {
  return client.delete(`/v1/comments/${commentId}`);
}

/** `PATCH /v1/posts/{id}`: the author edits the text or the audience (POST-003). */
export function updatePost(
  client: ApiClient,
  postId: string,
  changes: { body?: string; visibility?: 'public' | 'followers' | 'private' },
): Promise<Post> {
  return client.patch<Post>(`/v1/posts/${postId}`, { body: changes });
}

/** `DELETE /v1/posts/{id}`: gone from feeds and the profile at once. */
export function deletePost(client: ApiClient, postId: string): Promise<void> {
  return client.delete(`/v1/posts/${postId}`);
}

export type FeedFeedback = 'hide' | 'not_interested' | 'see_less_author';

/** `POST /v1/feed/feedback` (FEED-020 negative feedback): fewer stories like this one. */
export async function sendFeedFeedback(
  client: ApiClient,
  postId: string,
  kind: FeedFeedback,
): Promise<void> {
  await client.post('/v1/feed/feedback', { body: { post_id: postId, kind } });
}

/** `POST /v1/posts/{id}/shares`: a link to the public story (opens the guest preview). */
export async function shareLink(client: ApiClient, postId: string): Promise<string> {
  const link = await client.post<{ url: string }>(`/v1/posts/${postId}/shares`, {
    body: { channel: 'system_share_sheet' },
  });
  return link.url;
}

/** `PUT`/`DELETE /v1/posts/{id}/bookmark` (POST-005): private, only I see what I saved. */
export function setBookmark(client: ApiClient, postId: string, on: boolean): Promise<unknown> {
  return on
    ? client.put(`/v1/posts/${postId}/bookmark`)
    : client.delete(`/v1/posts/${postId}/bookmark`);
}

/** `GET /v1/users/me/bookmarks`: my saved stories, newest save first. */
export function fetchBookmarks(client: ApiClient, cursor?: string): Promise<Page<Post>> {
  return client.get<Page<Post>>('/v1/users/me/bookmarks', { query: { cursor, limit: 20 } });
}

export interface NewPost {
  kind: PostKind;
  body: string;
  visibility: 'public' | 'followers' | 'private';
  destination: DestinationSummary | null;
  /** A public place in that destination; the post is then filed under the place (POST-002). */
  place?: { id: string; name: string } | null;
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
      ...(post.place
        ? { location_precision: 'place', place_id: post.place.id }
        : {
            location_precision: post.destination ? 'destination' : 'none',
            ...(post.destination ? { destination_id: post.destination.id } : {}),
          }),
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
