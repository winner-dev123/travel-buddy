/**
 * Cursor pagination envelope shared by every list endpoint (docs/02 §5).
 * Cursors are opaque, server-signed and expiring: never parse or build them.
 */
export interface PageInfo {
  next_cursor: string | null;
  has_more: boolean;
  /**
   * Set by snapshot-based lists (e.g. the ranked feed) when the server-side
   * snapshot expired and a fresh first page was returned instead.
   */
  reset?: boolean;
}

export interface CursorPage<T> {
  data: T[];
  page: PageInfo;
}

export interface CursorPageParams {
  cursor?: string | null;
  /** 1–100, server default 20. */
  limit?: number;
}

/** For TanStack Query `getNextPageParam`. */
export function getNextCursor<T>(page: CursorPage<T>): string | undefined {
  return page.page.has_more && page.page.next_cursor ? page.page.next_cursor : undefined;
}
