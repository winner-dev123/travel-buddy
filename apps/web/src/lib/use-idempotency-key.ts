'use client';

import { useCallback, useRef } from 'react';
import { newIdempotencyKey } from '@travelbuddy/api-client';

/**
 * One Idempotency-Key per request content. Retrying the same content (after a timeout or a lost
 * response) reuses the key, so the platform replays the original 201 instead of creating a duplicate.
 * Different content gets a fresh key, because the platform answers 409 for a reused key with another
 * body. Call `done()` once the request succeeded.
 */
export function useIdempotencyKey() {
  const last = useRef<{ fingerprint: string; key: string } | null>(null);
  const keyFor = useCallback((content: unknown) => {
    const fingerprint = JSON.stringify(content);
    if (last.current?.fingerprint !== fingerprint) last.current = { fingerprint, key: newIdempotencyKey() };
    return last.current.key;
  }, []);
  const done = useCallback(() => {
    last.current = null;
  }, []);
  return { keyFor, done };
}
