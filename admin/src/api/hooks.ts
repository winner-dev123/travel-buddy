import { useInfiniteQuery } from '@tanstack/react-query';

import type { Page } from './types';

/** A cursor-paged list ("Load more"), flattened. */
export function usePaged<T>(
  key: readonly unknown[],
  fetchPage: (cursor: string | null) => Promise<Page<T>>,
  enabled = true,
) {
  const query = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.page.has_more ? last.page.next_cursor : undefined),
    enabled,
  });
  return { ...query, items: query.data?.pages.flatMap((p) => p.data) ?? [] };
}
