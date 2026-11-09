import { ApiClient, createApi, fetchTransport, type Api } from '@travelbuddy/api-client';

/** Reads the double-submit CSRF token cookie set by proxy.ts (ADR-0011). */
export function readCsrfToken(): string {
  if (typeof document === 'undefined') return '';
  const match = /(?:^|;\s*)tb_csrf=([^;]+)/.exec(document.cookie);
  return match?.[1] ? decodeURIComponent(match[1]) : '';
}

let api: Api | undefined;

/**
 * Browser-side API. Always talks to the same-origin BFF (`/api/v1/*`), never to the platform
 * directly, and never sees tokens: the session lives in an HTTP-only cookie.
 */
export function browserApi(): Api {
  return (api ??= createApi(
    new ApiClient(
      fetchTransport({
        baseUrl: '/api',
        credentials: 'same-origin',
        getHeaders: () => ({ 'X-CSRF-Token': readCsrfToken() }),
      }),
      { headers: () => ({ 'Accept-Language': document.documentElement.lang || 'en' }) },
    ),
  ));
}

/** POST helper for the BFF auth endpoints (`/api/auth/*`), which are not part of `/v1`. */
export async function postAuth<T>(path: string, body?: unknown): Promise<{ ok: boolean; status: number; data: T }> {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': readCsrfToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await response.json().catch(() => ({}))) as T;
  return { ok: response.ok, status: response.status, data };
}
