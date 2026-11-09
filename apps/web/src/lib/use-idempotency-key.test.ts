import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useIdempotencyKey } from './use-idempotency-key';

describe('useIdempotencyKey', () => {
  it('reuses the key for retries of the same content and rotates it for new content or after success', () => {
    const { result } = renderHook(() => useIdempotencyKey());
    const first = result.current.keyFor({ body: 'Hello', kind: 'tip' });
    expect(result.current.keyFor({ body: 'Hello', kind: 'tip' })).toBe(first);

    const edited = result.current.keyFor({ body: 'Hello!', kind: 'tip' });
    expect(edited).not.toBe(first);

    result.current.done();
    expect(result.current.keyFor({ body: 'Hello!', kind: 'tip' })).not.toBe(edited);
  });
});
