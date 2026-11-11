import { focusManager, QueryClient } from '@tanstack/react-query';
import { AppState, type AppStateStatus, Platform } from 'react-native';

import { ApiNetworkError, ApiProblem } from '@/api/errors';

const MAX_RETRIES = 2;

/** Retry transient failures only. 4xx problems are deterministic. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_RETRIES) {
    return false;
  }
  if (error instanceof ApiNetworkError) {
    return error.kind !== 'aborted';
  }
  if (error instanceof ApiProblem) {
    return error.status >= 500 || error.status === 429;
  }
  return false;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        networkMode: 'online',
      },
      mutations: {
        // Mutations are retried by the caller with the SAME Idempotency-Key.
        retry: false,
        networkMode: 'online',
      },
    },
  });
}

/**
 * React Native has no window focus: report the app coming to the foreground instead, so stale
 * queries (the feed, messages, server feature flags) refresh when the traveller returns.
 * Returns the unsubscribe function.
 */
export function refetchWhenForegrounded(): () => void {
  if (Platform.OS === 'web') {
    return () => undefined;
  }
  focusManager.setEventListener((setFocused) => {
    const subscription = AppState.addEventListener('change', (status: AppStateStatus) =>
      setFocused(status === 'active'),
    );
    return () => subscription.remove();
  });
  return () => focusManager.setEventListener(() => () => undefined);
}
