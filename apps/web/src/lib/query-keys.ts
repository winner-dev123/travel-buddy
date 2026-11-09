import type { FeedQuery } from '@travelbuddy/api-client';

/** Single source of TanStack Query keys (docs/web/01 §9). Invalidate by prefix. */
export const qk = {
  me: () => ['me'] as const,
  feed: (q: Omit<FeedQuery, 'cursor'>) => ['feed', q.tab, q.destination_id ?? null, q.near ?? null, q.radius_km ?? null] as const,
  feedAll: () => ['feed'] as const,
  destinationSearch: (q: string) => ['destinations', 'search', q] as const,
  post: (id: string) => ['post', id] as const,
  comments: (postId: string) => ['post', postId, 'comments'] as const,
};
