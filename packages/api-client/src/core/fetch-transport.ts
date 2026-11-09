import { buildQueryString } from './client';
import type { ApiRequest, RawResponse, Transport } from './types';

export interface FetchTransportOptions {
  /** Absolute platform origin (`https://api.example.com`) or a same-origin prefix (`/api`). */
  baseUrl: string;
  /** Extra headers per request, e.g. `Authorization` (server) or `X-CSRF-Token` (browser). */
  getHeaders?: () => Record<string, string> | Promise<Record<string, string>>;
  fetch?: typeof fetch;
  credentials?: RequestCredentials;
  /** Abort requests that take longer than this. Default 15 s. */
  timeoutMs?: number;
}

function headersToRecord(headers: Headers): Record<string, string> {
  const out: Record<string, string> = {};
  headers.forEach((value, key) => {
    out[key.toLowerCase()] = value;
  });
  return out;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return undefined;
  const type = response.headers.get('content-type') ?? '';
  const text = await response.text();
  if (!text) return undefined;
  if (type.includes('json')) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  }
  return text;
}

export function fetchTransport(options: FetchTransportOptions): Transport {
  const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  const base = options.baseUrl.replace(/\/+$/, '');

  return {
    async send(request: ApiRequest): Promise<RawResponse> {
      const headers: Record<string, string> = {
        Accept: 'application/json, application/problem+json',
        ...(await options.getHeaders?.()),
        ...request.headers,
      };
      let body: string | undefined;
      if (request.body !== undefined) {
        headers['Content-Type'] = 'application/json';
        body = JSON.stringify(request.body);
      }
      if (request.idempotencyKey) headers['Idempotency-Key'] = request.idempotencyKey;
      if (request.ifMatch !== undefined) headers['If-Match'] = `"${request.ifMatch}"`;
      if (request.auditJustification) headers['X-Audit-Justification'] = request.auditJustification;

      const init: RequestInit & { next?: { revalidate?: number | false; tags?: string[] } } = {
        method: request.method,
        headers,
        body,
        credentials: options.credentials,
        redirect: 'manual',
      };
      if (request.cache === 'no-store') init.cache = 'no-store';
      else if (request.cache) init.next = request.cache;

      const timeout = AbortSignal.timeout(options.timeoutMs ?? 15_000);
      init.signal = request.signal ? AbortSignal.any([request.signal, timeout]) : timeout;

      const url = `${base}${request.path}${buildQueryString(request.query)}`;
      const response = await doFetch(url, init);
      return {
        status: response.status,
        headers: headersToRecord(response.headers),
        body: await parseBody(response),
      };
    },
  };
}
