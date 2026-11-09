export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];

/** Cache hint for transports that support it (Next.js `fetch`). Ignored elsewhere. */
export type CacheHint = 'no-store' | { revalidate?: number | false; tags?: string[] };

export interface ApiRequest {
  method: HttpMethod;
  /** Platform path including the version prefix, e.g. `/v1/destinations`. */
  path: string;
  query?: Record<string, QueryValue>;
  body?: unknown;
  headers?: Record<string, string>;
  /** Sent as `Idempotency-Key` (doc 02 §5). */
  idempotencyKey?: string;
  /** Sent as `If-Match: "<version>"` for versioned aggregates. */
  ifMatch?: string | number;
  /**
   * Sent as `X-Audit-Justification` (10–500 chars). Required by the platform on every /v1/admin
   * mutation and on sensitive admin reads (ADM-009); missing → 400 justification_required.
   */
  auditJustification?: string;
  signal?: AbortSignal;
  cache?: CacheHint;
}

/** Transport-level response. Header names are lower case. Never throws for HTTP error statuses. */
export interface RawResponse {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

export interface Transport {
  send(request: ApiRequest): Promise<RawResponse>;
}
