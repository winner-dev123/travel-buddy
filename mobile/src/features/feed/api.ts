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
  list: (tab: FeedTab | 'guest') => ['feed', tab] as const,
  post: (id: string) => ['post', id] as const,
  comments: (id: string) => ['post', id, 'comments'] as const,
};

/** `GET /v1/feed` (signed in) — the server explains its fallback choice in `context`. */
export function fetchFeed(client: ApiClient, tab: FeedTab, cursor?: string): Promise<FeedPage> {
  return client.get<FeedPage>('/v1/feed', { query: { tab, cursor, limit: 20 } });
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
