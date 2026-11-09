import { describe, expect, it } from 'vitest';
import type { FeedPage } from '@travelbuddy/domain-types';
import { applyFeedReset } from './feed-reset';

const page = (ids: string[], reset = false): FeedPage =>
  ({
    data: ids.map((id) => ({ id })),
    page: { next_cursor: `after-${ids.at(-1)}`, has_more: true, reset },
    context: { destination: null, source: 'global', radius_km: null },
  }) as unknown as FeedPage;

describe('applyFeedReset', () => {
  it('leaves an ordinary list alone', () => {
    const data = { pages: [page(['a', 'b']), page(['c', 'd'])], pageParams: [null, 'c1'] };
    expect(applyFeedReset(data)).toBe(data);
  });

  it('replaces everything before a reset page (expired snapshot), so posts are not duplicated', () => {
    const data = { pages: [page(['a', 'b']), page(['c', 'd']), page(['a', 'x'], true)], pageParams: [null, 'c1', 'c2'] };
    const applied = applyFeedReset(data);
    expect(applied.pages.flatMap((p) => p.data.map((post) => post.id))).toEqual(['a', 'x']);
    expect(applied.pageParams).toEqual(['c2']);
  });

  it('ignores reset on the first page and keeps pages after the latest reset', () => {
    const data = {
      pages: [page(['a'], true), page(['b'], true), page(['c']), page(['d'], true), page(['e'])],
      pageParams: [null, 'c1', 'c2', 'c3', 'c4'],
    };
    expect(applyFeedReset(data).pages.flatMap((p) => p.data.map((post) => post.id))).toEqual(['d', 'e']);
  });
});
