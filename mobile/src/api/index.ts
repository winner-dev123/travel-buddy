import { randomUUID } from 'expo-crypto';

import { useSessionStore } from '@/auth/sessionStore';
import { tokenStore } from '@/auth/tokenStore';
import { getApiBaseUrl } from '@/config/env';
import { i18n } from '@/i18n';

import { ApiClient } from './client';

let defaultClient: ApiClient | undefined;
let refresher: (() => Promise<boolean>) | undefined;

/** Installed at startup by the session layer (it owns the refresh token). */
export function setAccessTokenRefresher(refresh: () => Promise<boolean>): void {
  refresher = refresh;
}

/**
 * The app-wide client, created lazily so that a missing
 * `EXPO_PUBLIC_API_BASE_URL` fails at first use with a clear message.
 *
 * Access tokens are refreshed transparently on `401 token_expired` (see
 * `setAccessTokenRefresher`).
 */
export function getApiClient(): ApiClient {
  defaultClient ??= new ApiClient({
    baseUrl: getApiBaseUrl(),
    getAccessToken: () => tokenStore.getAccessToken(),
    getLocale: () => i18n.language || 'en',
    generateId: randomUUID,
    refreshAccessToken: async () => (refresher ? refresher() : false),
    hasSession: () => useSessionStore.getState().status === 'signed_in',
  });
  return defaultClient;
}

export { ApiClient } from './client';
export type { ApiClientConfig, HttpMethod, QueryValue, RequestOptions } from './client';
export { ApiNetworkError, ApiProblem, ApiUsageError, isProblemDocument } from './errors';
export type { NetworkFailureKind, ProblemDocument, ProblemFieldError } from './errors';
export { getNextCursor } from './pagination';
export type { CursorPage, CursorPageParams, PageInfo } from './pagination';
