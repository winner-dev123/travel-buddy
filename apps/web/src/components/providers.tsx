'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { isApiError, isRetryable } from '@travelbuddy/api-client';

/** Client providers. TanStack Query defaults follow docs/web/01 §9. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => failureCount < 2 && isRetryable(error),
          },
          mutations: {
            retry: (failureCount, error) => failureCount < 1 && isApiError(error) && error.status === 0,
          },
        },
      }),
  );
  useEffect(() => {
    // Marks the document as interactive; E2E tests wait for it instead of arbitrary timeouts.
    document.documentElement.dataset.hydrated = 'true';
  }, []);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
