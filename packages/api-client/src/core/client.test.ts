import { describe, expect, it, vi } from 'vitest';
import { ApiClient, buildQueryString } from './client';
import { ApiError, isRetryable } from './errors';
import { fetchTransport } from './fetch-transport';

describe('buildQueryString', () => {
  it('skips empty values and repeats array keys', () => {
    expect(buildQueryString({ a: 1, b: undefined, c: null, d: '', e: ['x', 'y'], f: true })).toBe('?a=1&e=x&e=y&f=true');
    expect(buildQueryString({})).toBe('');
  });
});

describe('fetchTransport + ApiClient', () => {
  it('sends JSON, idempotency and If-Match headers and parses the body', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify({ ok: true }), { status: 201, headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'r1' } }),
    );
    const client = new ApiClient(
      fetchTransport({ baseUrl: 'https://api.test/', fetch: fetchMock as unknown as typeof fetch, getHeaders: () => ({ Authorization: 'Bearer t' }) }),
      { headers: { 'Accept-Language': 'fr' } },
    );
    const body = await client.request<{ ok: boolean }>({
      method: 'POST', path: '/v1/posts', query: { a: 1 }, body: { x: 1 }, idempotencyKey: 'k1', ifMatch: 3,
    });
    expect(body).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('https://api.test/v1/posts?a=1');
    const headers = init!.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer t');
    expect(headers['Accept-Language']).toBe('fr');
    expect(headers['Idempotency-Key']).toBe('k1');
    expect(headers['If-Match']).toBe('"3"');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('turns problem+json into ApiError with the stable code and request id', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ type: 'x', title: 'Premium required', status: 403, code: 'entitlement_required', entitlement: 'groups.create', request_id: 'req-9' }),
        { status: 403, headers: { 'Content-Type': 'application/problem+json' } },
      ),
    );
    const client = new ApiClient(fetchTransport({ baseUrl: '', fetch: fetchMock as unknown as typeof fetch }));
    const error = await client.request({ method: 'POST', path: '/v1/groups' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.code).toBe('entitlement_required');
    expect(apiError.problem.entitlement).toBe('groups.create');
    expect(apiError.requestId).toBe('req-9');
    expect(apiError.is('entitlement_required', 'forbidden')).toBe(true);
    expect(isRetryable(apiError)).toBe(false);
  });

  it('maps non-problem errors by status and network failures to network_error', async () => {
    const html = vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502, headers: { 'Retry-After': '5' } }));
    const c1 = new ApiClient(fetchTransport({ baseUrl: '', fetch: html as unknown as typeof fetch }));
    const e1 = (await c1.request({ method: 'GET', path: '/v1/x' }).catch((e: unknown) => e)) as ApiError;
    expect(e1.code).toBe('service_unavailable');
    expect(e1.retryAfterSeconds).toBe(5);
    expect(isRetryable(e1)).toBe(true);

    const offline = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const c2 = new ApiClient(fetchTransport({ baseUrl: '', fetch: offline as unknown as typeof fetch }));
    const e2 = (await c2.request({ method: 'GET', path: '/v1/x' }).catch((e: unknown) => e)) as ApiError;
    expect(e2.code).toBe('network_error');
    expect(e2.status).toBe(0);
  });
});
