import type { Problem } from './types';

/** An RFC 9457 problem from the API (or a network failure, `code: network_error`). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;
  readonly fieldErrors: { field: string; message: string }[];

  constructor(problem: Problem) {
    super(problem.detail || problem.title || problem.code);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
    this.requestId = problem.request_id;
    this.fieldErrors = (problem.errors ?? []).map((e) => ({ field: e.field, message: e.message }));
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  query?: Query;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export function buildUrl(base: string, path: string, query?: Query): string {
  const url = new URL(base + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** One HTTP call; JSON in and out, problems turned into `ApiError`. Never logs bodies. */
export async function requestJson<T>(url: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
  let body: string | undefined;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }
  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError({ status: 0, code: 'network_error', detail: 'The server could not be reached.' });
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }
  if (!response.ok) {
    const problem = (parsed ?? {}) as Partial<Problem>;
    throw new ApiError({
      status: response.status,
      code: problem.code ?? `http_${response.status}`,
      detail: problem.detail,
      title: problem.title,
      request_id: problem.request_id ?? response.headers.get('X-Request-ID') ?? undefined,
      errors: problem.errors,
    });
  }
  return parsed as T;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
