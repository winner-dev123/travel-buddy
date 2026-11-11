import { focusManager } from '@tanstack/react-query';
import { AppState, type AppStateStatus } from 'react-native';

import { ApiNetworkError, ApiProblem } from '@/api/errors';

import { refetchWhenForegrounded, shouldRetry } from '../queryClient';

describe('refetchWhenForegrounded', () => {
  it('reports the app coming to the foreground as focus, so stale queries refresh', () => {
    let listener: ((status: AppStateStatus) => void) | undefined;
    const remove = jest.fn();
    const spy = jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, handler) => {
      listener = handler as (status: AppStateStatus) => void;
      return { remove } as unknown as ReturnType<typeof AppState.addEventListener>;
    });

    const stop = refetchWhenForegrounded();
    listener?.('background');
    expect(focusManager.isFocused()).toBe(false);
    listener?.('active');
    expect(focusManager.isFocused()).toBe(true);

    stop();
    expect(remove).toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe('shouldRetry', () => {
  it('retries transient failures only', () => {
    const problem = (status: number) =>
      new ApiProblem(
        { type: 'about:blank', title: 'x', status, code: status === 429 ? 'rate_limited' : 'x' },
        'r1',
      );
    expect(shouldRetry(0, new ApiNetworkError('timeout', 'r1'))).toBe(true);
    expect(shouldRetry(0, problem(503))).toBe(true);
    expect(shouldRetry(0, problem(429))).toBe(true);
    expect(shouldRetry(0, problem(403))).toBe(false); // e.g. feature_disabled: retrying can't help
    expect(shouldRetry(2, problem(503))).toBe(false);
  });
});
