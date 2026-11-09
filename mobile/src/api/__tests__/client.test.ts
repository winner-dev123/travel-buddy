// req: NFR-011
import { ApiClient, type ApiClientConfig } from '../client';
import { ApiNetworkError, ApiProblem, ApiUsageError } from '../errors';

interface FakeResponseInit {
  status?: number;
  statusText?: string;
  headers?: Record<string, string>;
  body?: string;
}

function fakeResponse({
  status = 200,
  statusText = '',
  headers = {},
  body = '',
}: FakeResponseInit) {
  const lowerHeaders = Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]),
  );
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    headers: { get: (name: string) => lowerHeaders[name.toLowerCase()] ?? null },
    json: async () => JSON.parse(body) as unknown,
    text: async () => body,
  } as unknown as Response;
}

function jsonResponse(payload: unknown, status = 200) {
  return fakeResponse({
    status,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

function problemResponse(payload: unknown, status: number, headers: Record<string, string> = {}) {
  return fakeResponse({
    status,
    headers: { 'Content-Type': 'application/problem+json', ...headers },
    body: JSON.stringify(payload),
  });
}

function setup(overrides: Partial<ApiClientConfig> = {}, response?: Response) {
  let counter = 0;
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    return response ?? jsonResponse({ ok: true });
  });
  const client = new ApiClient({
    baseUrl: 'https://api.example.test/',
    getAccessToken: () => 'access-token-123',
    getLocale: () => 'pt-BR',
    generateId: () => `00000000-0000-4000-8000-00000000000${counter++}`,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    ...overrides,
  });
  const lastCall = () => {
    const call = fetchImpl.mock.calls.at(-1);
    if (!call) throw new Error('fetch was not called');
    const [url, init] = call;
    return {
      url: String(url),
      init: init ?? {},
      headers: (init?.headers ?? {}) as Record<string, string>,
    };
  };
  return { client, fetchImpl, lastCall };
}

describe('ApiClient request construction', () => {
  it('sends correlation, locale and auth headers and builds the URL', async () => {
    const { client, lastCall } = setup();

    await client.get('/v1/feed', {
      query: { tab: 'for_you', limit: 20, tag: ['food', 'beach'], cursor: undefined, x: null },
    });

    const { url, init, headers } = lastCall();
    expect(url).toBe('https://api.example.test/v1/feed?tab=for_you&limit=20&tag=food&tag=beach');
    expect(init.method).toBe('GET');
    expect(headers['X-Request-ID']).toBe('00000000-0000-4000-8000-000000000000');
    expect(headers['Accept-Language']).toBe('pt-BR');
    expect(headers.Authorization).toBe('Bearer access-token-123');
    expect(headers['Idempotency-Key']).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it('generates a new request ID per request', async () => {
    const { client, fetchImpl } = setup();
    await client.get('/v1/a');
    await client.get('/v1/b');
    const ids = fetchImpl.mock.calls.map(
      ([, init]) => (init?.headers as Record<string, string>)['X-Request-ID'],
    );
    expect(new Set(ids).size).toBe(2);
  });

  it('omits Authorization when signed out', async () => {
    const { client, lastCall } = setup({ getAccessToken: () => null });
    await client.get('/v1/destinations/search', { query: { q: 'Rio' } });
    expect(lastCall().headers.Authorization).toBeUndefined();
  });

  it('sends JSON body, Idempotency-Key and If-Match on mutations', async () => {
    const { client, lastCall } = setup();
    const key = client.newIdempotencyKey();

    await client.post('/v1/posts', {
      body: { body: 'Sunset at Arpoador' },
      idempotencyKey: key,
      ifMatchVersion: 3,
    });

    const { init, headers } = lastCall();
    expect(init.method).toBe('POST');
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['Idempotency-Key']).toBe(key);
    expect(headers['If-Match']).toBe('"3"');
    expect(init.body).toBe(JSON.stringify({ body: 'Sunset at Arpoador' }));
  });

  it('rejects an Idempotency-Key on GET and relative paths', async () => {
    const { client, fetchImpl } = setup();
    await expect(
      client.request('GET', '/v1/feed', { idempotencyKey: 'abc' }),
    ).rejects.toBeInstanceOf(ApiUsageError);
    await expect(client.get('v1/feed')).rejects.toBeInstanceOf(ApiUsageError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe('ApiClient responses', () => {
  it('returns parsed JSON', async () => {
    const { client } = setup(
      {},
      jsonResponse({ data: [], page: { next_cursor: null, has_more: false } }),
    );
    await expect(client.get('/v1/feed')).resolves.toEqual({
      data: [],
      page: { next_cursor: null, has_more: false },
    });
  });

  it('returns undefined for 204 No Content', async () => {
    const { client } = setup({}, fakeResponse({ status: 204 }));
    await expect(client.delete('/v1/posts/1')).resolves.toBeUndefined();
  });

  it('parses application/problem+json into ApiProblem', async () => {
    const problem = {
      type: 'https://errors.travelbuddy.app/validation_failed',
      title: 'Validation failed',
      status: 422,
      detail: 'One or more fields are invalid.',
      instance: '/v1/posts',
      code: 'validation_failed',
      request_id: 'req-from-server',
      errors: [
        { field: 'body', code: 'too_long', message: 'Must be at most 5000 characters.' },
        { field: 'body', code: 'blocked_term', message: 'Contains a blocked term.' },
      ],
    };
    const { client } = setup({}, problemResponse(problem, 422));

    const error = await client.post('/v1/posts', { body: {} }).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiProblem);
    const apiProblem = error as ApiProblem;
    expect(apiProblem.status).toBe(422);
    expect(apiProblem.code).toBe('validation_failed');
    expect(apiProblem.type).toBe(problem.type);
    expect(apiProblem.title).toBe('Validation failed');
    expect(apiProblem.detail).toBe(problem.detail);
    expect(apiProblem.instance).toBe('/v1/posts');
    expect(apiProblem.requestId).toBe('req-from-server');
    expect(apiProblem.fieldErrors()).toEqual({
      body: ['Must be at most 5000 characters.', 'Contains a blocked term.'],
    });
  });

  it('falls back to the response X-Request-ID header for correlation', async () => {
    const problem = {
      type: 'about:blank',
      title: 'Forbidden',
      status: 403,
      code: 'entitlement_required',
    };
    const { client } = setup({}, problemResponse(problem, 403, { 'X-Request-ID': 'req-header' }));

    const error = (await client.post('/v1/groups').catch((e: unknown) => e)) as ApiProblem;

    expect(error.code).toBe('entitlement_required');
    expect(error.requestId).toBe('req-header');
    expect(error.errors).toEqual([]);
  });

  it('synthesizes unexpected_response for non-problem error bodies', async () => {
    const { client } = setup(
      {},
      fakeResponse({
        status: 502,
        statusText: 'Bad Gateway',
        headers: { 'Content-Type': 'text/html' },
        body: '<html>bad gateway</html>',
      }),
    );

    const error = (await client.get('/v1/feed').catch((e: unknown) => e)) as ApiProblem;

    expect(error).toBeInstanceOf(ApiProblem);
    expect(error.status).toBe(502);
    expect(error.code).toBe('unexpected_response');
    expect(error.requestId).toBe('00000000-0000-4000-8000-000000000000');
  });

  it('treats a malformed problem body as unexpected_response', async () => {
    const { client } = setup({}, problemResponse({ title: 'missing fields' }, 500));
    const error = (await client.get('/v1/feed').catch((e: unknown) => e)) as ApiProblem;
    expect(error.code).toBe('unexpected_response');
    expect(error.status).toBe(500);
  });
});

describe('ApiClient network failures', () => {
  it('maps a rejected fetch to ApiNetworkError(offline)', async () => {
    const { client } = setup({
      fetchImpl: (async () => {
        throw new TypeError('Network request failed');
      }) as unknown as typeof fetch,
    });

    const error = (await client.get('/v1/feed').catch((e: unknown) => e)) as ApiNetworkError;

    expect(error).toBeInstanceOf(ApiNetworkError);
    expect(error.kind).toBe('offline');
    expect(error.requestId).toBe('00000000-0000-4000-8000-000000000000');
  });

  const hangingFetch = ((_input: RequestInfo | URL, init?: RequestInit) =>
    new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new Error('AbortError')));
    })) as unknown as typeof fetch;

  it('maps a timeout to ApiNetworkError(timeout)', async () => {
    const { client } = setup({ fetchImpl: hangingFetch, timeoutMs: 10 });
    const error = (await client.get('/v1/feed').catch((e: unknown) => e)) as ApiNetworkError;
    expect(error).toBeInstanceOf(ApiNetworkError);
    expect(error.kind).toBe('timeout');
  });

  it('maps a caller abort to ApiNetworkError(aborted)', async () => {
    const { client } = setup({ fetchImpl: hangingFetch });
    const controller = new AbortController();
    const pending = client.get('/v1/feed', { signal: controller.signal });
    controller.abort();
    const error = (await pending.catch((e: unknown) => e)) as ApiNetworkError;
    expect(error.kind).toBe('aborted');
  });
});
