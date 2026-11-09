import type { ErrorCode, FieldError, Problem } from '@travelbuddy/domain-types';
import type { RawResponse } from './types';

const STATUS_FALLBACK_CODES: Record<number, ErrorCode> = {
  400: 'validation_failed',
  401: 'unauthenticated',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  412: 'precondition_failed',
  413: 'payload_too_large',
  415: 'unsupported_media_type',
  422: 'validation_failed',
  429: 'rate_limited',
  503: 'service_unavailable',
};

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as Problem).status === 'number' &&
    typeof (value as Problem).code === 'string'
  );
}

/**
 * The only error type API functions throw. UI code switches on `code` (stable, doc 02 §5),
 * never on `message` or `problem.title`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly problem: Problem;
  readonly requestId: string | undefined;
  readonly retryAfterSeconds: number | undefined;

  constructor(problem: Problem, retryAfterSeconds?: number) {
    super(problem.detail ?? problem.title);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
    this.problem = problem;
    this.requestId = problem.request_id;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  is(...codes: ErrorCode[]): boolean {
    return codes.includes(this.code);
  }

  get fieldErrors(): FieldError[] {
    return this.problem.errors ?? [];
  }

  static fromResponse(response: RawResponse): ApiError {
    const retryAfter = Number(response.headers['retry-after']);
    const retry = Number.isFinite(retryAfter) ? retryAfter : undefined;
    if (isProblem(response.body)) {
      return new ApiError(
        { ...response.body, request_id: response.body.request_id ?? response.headers['x-request-id'] },
        retry,
      );
    }
    const code = STATUS_FALLBACK_CODES[response.status] ?? 'service_unavailable';
    return new ApiError(
      {
        type: 'about:blank',
        title: `HTTP ${response.status}`,
        status: response.status,
        code,
        request_id: response.headers['x-request-id'],
      },
      retry,
    );
  }

  static network(cause: unknown): ApiError {
    const error = new ApiError({
      type: 'about:blank',
      title: 'Network error',
      status: 0,
      code: 'network_error',
      detail: cause instanceof Error ? cause.message : undefined,
    });
    (error as { cause?: unknown }).cause = cause;
    return error;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/** True for failures worth retrying automatically (network, 429, 5xx). */
export function isRetryable(error: unknown): boolean {
  if (!isApiError(error)) return false;
  return error.status === 0 || error.status === 429 || error.status >= 500;
}
