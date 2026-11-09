/**
 * Error types raised by the API client. Callers branch on `instanceof` and, for
 * server errors, on the stable `code` — never on `title` or `detail`, which are
 * human-readable and may be localized.
 */

export interface ProblemFieldError {
  field: string;
  code: string;
  message: string;
}

/** RFC 9457 problem document as returned by the backend (docs/02 §5). */
export interface ProblemDocument {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  code: string;
  request_id?: string;
  errors?: ProblemFieldError[];
}

/** The server answered with an error status. */
export class ApiProblem extends Error {
  override name = 'ApiProblem';
  readonly type: string;
  readonly title: string;
  readonly status: number;
  readonly detail: string | undefined;
  readonly instance: string | undefined;
  readonly code: string;
  readonly requestId: string;
  readonly errors: readonly ProblemFieldError[];

  constructor(problem: ProblemDocument, requestId: string) {
    super(problem.detail ?? problem.title);
    this.type = problem.type;
    this.title = problem.title;
    this.status = problem.status;
    this.detail = problem.detail;
    this.instance = problem.instance;
    this.code = problem.code;
    this.requestId = problem.request_id ?? requestId;
    this.errors = problem.errors ?? [];
  }

  /** Field-level validation messages keyed by field path. */
  fieldErrors(): Record<string, string[]> {
    const result: Record<string, string[]> = {};
    for (const error of this.errors) {
      (result[error.field] ??= []).push(error.message);
    }
    return result;
  }
}

export type NetworkFailureKind = 'offline' | 'timeout' | 'aborted';

/** The request never produced an HTTP response. */
export class ApiNetworkError extends Error {
  override name = 'ApiNetworkError';
  readonly kind: NetworkFailureKind;
  readonly requestId: string;

  constructor(kind: NetworkFailureKind, requestId: string, cause?: unknown) {
    super(`Network request failed (${kind})`, { cause });
    this.kind = kind;
    this.requestId = requestId;
  }
}

/** Shared request-shape guard: thrown for programmer errors before sending. */
export class ApiUsageError extends Error {
  override name = 'ApiUsageError';
}

function isFieldError(value: unknown): value is ProblemFieldError {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return typeof v.field === 'string' && typeof v.code === 'string' && typeof v.message === 'string';
}

/** Runtime validation of an untrusted problem body. */
export function isProblemDocument(value: unknown): value is ProblemDocument {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (
    typeof v.type === 'string' &&
    typeof v.title === 'string' &&
    typeof v.status === 'number' &&
    typeof v.code === 'string' &&
    (v.detail === undefined || typeof v.detail === 'string') &&
    (v.instance === undefined || typeof v.instance === 'string') &&
    (v.request_id === undefined || typeof v.request_id === 'string') &&
    (v.errors === undefined || (Array.isArray(v.errors) && v.errors.every(isFieldError)))
  );
}
