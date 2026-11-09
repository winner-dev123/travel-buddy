import { ApiError } from './errors';
import type { ApiRequest, QueryValue, RawResponse, Transport } from './types';

export interface ApiClientOptions {
  /** Headers added to every request (e.g. `Accept-Language`). Evaluated per request. */
  headers?: Record<string, string> | (() => Record<string, string>);
}

export class ApiClient {
  constructor(
    private readonly transport: Transport,
    private readonly options: ApiClientOptions = {},
  ) {}

  /** Sends a request and returns the parsed body, throwing `ApiError` on any failure. */
  async request<T>(request: ApiRequest): Promise<T> {
    const response = await this.send(request);
    return response.body as T;
  }

  /** Like `request` but also returns status and headers (ETag, rate-limit, mock marker). */
  async send(request: ApiRequest): Promise<RawResponse> {
    const defaults =
      typeof this.options.headers === 'function' ? this.options.headers() : this.options.headers;
    const merged: ApiRequest = { ...request, headers: { ...defaults, ...request.headers } };
    let response: RawResponse;
    try {
      response = await this.transport.send(merged);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw ApiError.network(error);
    }
    if (response.status >= 400) throw ApiError.fromResponse(response);
    return response;
  }
}

export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export function buildQueryString(query: Record<string, QueryValue> | undefined): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}
