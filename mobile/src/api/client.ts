import { ApiNetworkError, ApiProblem, ApiUsageError, isProblemDocument } from './errors';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type QueryValue = string | number | boolean | null | undefined | readonly string[];

export interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  /**
   * Idempotency key for retry-safe mutations. Generate it ONCE per user action
   * (`client.newIdempotencyKey()`) and reuse it for every retry of that action.
   */
  idempotencyKey?: string;
  /** Optimistic concurrency: sent as `If-Match: "<version>"`. */
  ifMatchVersion?: number;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Overrides the client default timeout. */
  timeoutMs?: number;
}

export interface ApiClientConfig {
  baseUrl: string;
  /** In-memory access token, or null when signed out. */
  getAccessToken: () => string | null;
  /** Current UI locale (BCP 47) for `Accept-Language`. */
  getLocale: () => string;
  /** UUID v4 generator used for request IDs and idempotency keys. */
  generateId: () => string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  /**
   * Called once when a request fails with `401 token_expired`; resolves `true` when a new access
   * token is in place, and the request is then retried once. Concurrent failures share one call.
   */
  refreshAccessToken?: () => Promise<boolean>;
  /**
   * True while signed in. A signed-in session without an access token (the app was opened
   * without a network and kept the session) refreshes before its first request.
   */
  hasSession?: () => boolean;
}

const DEFAULT_TIMEOUT_MS = 15_000;
const MUTATING_METHODS: ReadonlySet<HttpMethod> = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const REFRESH_PATH = '/v1/auth/refresh';

export class ApiClient {
  private readonly config: Required<ApiClientConfig>;
  private refreshing: Promise<boolean> | null = null;

  constructor(config: ApiClientConfig) {
    this.config = {
      fetchImpl: (input, init) => fetch(input, init),
      timeoutMs: DEFAULT_TIMEOUT_MS,
      refreshAccessToken: async () => false,
      hasSession: () => false,
      ...config,
      baseUrl: config.baseUrl.replace(/\/+$/, ''),
    };
  }

  /** One refresh at a time: concurrent `token_expired` failures wait for the same attempt. */
  private refreshOnce(): Promise<boolean> {
    this.refreshing ??= this.config
      .refreshAccessToken()
      .catch(() => false)
      .finally(() => {
        this.refreshing = null;
      });
    return this.refreshing;
  }

  newIdempotencyKey(): string {
    return this.config.generateId();
  }

  get<T>(path: string, options?: Omit<RequestOptions, 'body' | 'idempotencyKey'>): Promise<T> {
    return this.request<T>('GET', path, options);
  }

  post<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('POST', path, options);
  }

  put<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('PUT', path, options);
  }

  patch<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('PATCH', path, options);
  }

  delete<T = void>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('DELETE', path, options);
  }

  async request<T>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<T> {
    if (path !== REFRESH_PATH && !this.config.getAccessToken() && this.config.hasSession()) {
      await this.refreshOnce();
    }
    try {
      return await this.send<T>(method, path, options);
    } catch (error) {
      const expired =
        error instanceof ApiProblem && error.status === 401 && error.code === 'token_expired';
      if (!expired || path === REFRESH_PATH || !this.config.getAccessToken()) {
        throw error;
      }
      if (!(await this.refreshOnce())) {
        throw error;
      }
      return this.send<T>(method, path, options); // same idempotency key: safe to repeat
    }
  }

  private async send<T>(method: HttpMethod, path: string, options: RequestOptions): Promise<T> {
    if (!path.startsWith('/')) {
      throw new ApiUsageError(`API paths must start with "/": "${path}"`);
    }
    if (options.idempotencyKey !== undefined && !MUTATING_METHODS.has(method)) {
      throw new ApiUsageError(`Idempotency-Key is only valid on mutations, not ${method}`);
    }

    const requestId = this.config.generateId();
    const headers: Record<string, string> = {
      Accept: 'application/json, application/problem+json',
      'Accept-Language': this.config.getLocale(),
      'X-Request-ID': requestId,
      ...options.headers,
    };
    const token = this.config.getAccessToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    if (options.idempotencyKey !== undefined) {
      headers['Idempotency-Key'] = options.idempotencyKey;
    }
    if (options.ifMatchVersion !== undefined) {
      headers['If-Match'] = `"${options.ifMatchVersion}"`;
    }
    let body: string | undefined;
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.body);
    }

    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, options.timeoutMs ?? this.config.timeoutMs);
    const onCallerAbort = () => controller.abort();
    if (options.signal?.aborted) {
      controller.abort();
    }
    options.signal?.addEventListener('abort', onCallerAbort);

    let response: Response;
    try {
      response = await this.config.fetchImpl(this.buildUrl(path, options.query), {
        method,
        headers,
        body,
        signal: controller.signal,
      });
    } catch (error) {
      if (timedOut) {
        throw new ApiNetworkError('timeout', requestId, error);
      }
      if (options.signal?.aborted) {
        throw new ApiNetworkError('aborted', requestId, error);
      }
      throw new ApiNetworkError('offline', requestId, error);
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', onCallerAbort);
    }

    const responseRequestId = response.headers.get('X-Request-ID') ?? requestId;
    if (!response.ok) {
      throw await toApiProblem(response, responseRequestId);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    const text = await response.text();
    return (text.length > 0 ? JSON.parse(text) : undefined) as T;
  }

  private buildUrl(path: string, query?: Record<string, QueryValue>): string {
    const url = `${this.config.baseUrl}${path}`;
    if (!query) {
      return url;
    }
    const params: string[] = [];
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) {
        continue;
      }
      const values = Array.isArray(value) ? value : [String(value)];
      for (const item of values) {
        params.push(`${encodeURIComponent(key)}=${encodeURIComponent(item)}`);
      }
    }
    return params.length > 0 ? `${url}?${params.join('&')}` : url;
  }
}

async function toApiProblem(response: Response, requestId: string): Promise<ApiProblem> {
  const contentType = response.headers.get('Content-Type') ?? '';
  if (contentType.includes('application/problem+json')) {
    try {
      const parsed: unknown = await response.json();
      if (isProblemDocument(parsed)) {
        return new ApiProblem(parsed, requestId);
      }
    } catch {
      // Malformed body: fall through to the synthesized problem below.
    }
  }
  // Non-problem error (e.g. a proxy's HTML 502): synthesize a stable shape.
  return new ApiProblem(
    {
      type: 'about:blank',
      title: response.statusText || 'Unexpected response',
      status: response.status,
      code: 'unexpected_response',
    },
    requestId,
  );
}
