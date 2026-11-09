import type { InfiniteData } from '@tanstack/react-query';
import type { FeedPage } from '@travelbuddy/domain-types';

/**
 * Feed pages come from a ranked snapshot (15 min). When a cursor outlives it, the platform recomputes
 * and answers with `page.reset = true`: that page starts a new list and must replace, not extend, the
 * pages before it (contract `GET /v1/feed`). Keeps the pages from the latest reset onward.
 */
export function applyFeedReset<P>(data: InfiniteData<FeedPage, P>): InfiniteData<FeedPage, P> {
  let start = 0;
  data.pages.forEach((page, index) => {
    if (index > 0 && page.page.reset) start = index;
  });
  return start === 0 ? data : { pages: data.pages.slice(start), pageParams: data.pageParams.slice(start) };
}
