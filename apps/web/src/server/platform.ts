import 'server-only';
import { ApiClient, createApi, fetchTransport, type Api, type Transport } from '@travelbuddy/api-client';
import { env } from './env';

let transport: Transport | undefined;

/**
 * The single server-side way to reach the platform. In mock mode this is the in-process mock
 * adapter (dynamically imported so it never ships in live builds' hot paths); otherwise the
 * real FastAPI platform at API_BASE_URL.
 */
export async function platformTransport(): Promise<Transport> {
  if (transport) return transport;
  const e = env();
  if (e.apiMode === 'mock') {
    const { getSharedMockPlatform } = await import('@travelbuddy/api-client/mock');
    // Same key in every serverless instance, so mock sessions survive across instances (demo).
    transport = getSharedMockPlatform({ tokenSecret: e.sessionSecret }).transport;
  } else {
    transport = fetchTransport({ baseUrl: e.apiBaseUrl as string, timeoutMs: 10_000 });
  }
  return transport;
}

export interface ServerApiOptions {
  accessToken?: string | null;
  locale?: string;
  requestId?: string;
  /** Extra headers, e.g. the browser's User-Agent on login/register (session device names). */
  headers?: Record<string, string>;
}

export async function serverApi(options: ServerApiOptions = {}): Promise<Api> {
  const t = await platformTransport();
  return createApi(
    new ApiClient(t, {
      headers: () => ({
        ...(options.locale ? { 'Accept-Language': options.locale } : {}),
        ...(options.accessToken ? { Authorization: `Bearer ${options.accessToken}` } : {}),
        ...(options.requestId ? { 'X-Request-ID': options.requestId } : {}),
        ...options.headers,
      }),
    }),
  );
}

/** Anonymous API for public, cacheable pages. Never pass cookies or tokens here. */
export function publicApi(locale: string): Promise<Api> {
  return serverApi({ locale });
}

export function isMockMode(): boolean {
  return env().apiMode === 'mock';
}
