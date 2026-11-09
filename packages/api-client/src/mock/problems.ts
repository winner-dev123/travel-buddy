import type { ErrorCode, FieldError } from '@travelbuddy/domain-types';

export interface MockProblem {
  type?: string;
  title: string;
  status: number;
  code: ErrorCode;
  detail?: string;
  errors?: FieldError[];
  /** RFC 9457 extension members (e.g. terms_version on consent_required). */
  [extension: string]: unknown;
}

/** Thrown by mock handlers; converted to an `application/problem+json` response. */
export class MockHttpError extends Error {
  constructor(
    readonly problem: MockProblem,
    readonly headers: Record<string, string> = {},
  ) {
    super(problem.detail ?? problem.title);
  }
}

const TITLES: Partial<Record<string, string>> = {
  validation_failed: 'Validation failed',
  unauthenticated: 'Authentication required',
  token_expired: 'Access token expired',
  forbidden: 'Forbidden',
  not_found: 'Not found',
  conflict: 'Conflict',
  idempotency_key_reused: 'Idempotency key reused with a different request',
  age_restricted: 'Age requirement not met',
  feature_not_available_in_mock: 'Not available in mock mode',
};

export function problem(status: number, code: ErrorCode, detail?: string, errors?: FieldError[]): MockHttpError {
  return new MockHttpError({
    type: `https://errors.travelbuddy.app/${code}`,
    title: TITLES[code] ?? code,
    status,
    code,
    detail,
    errors,
  });
}

export const notFound = (detail = 'The resource does not exist or is not visible to you.') => problem(404, 'not_found', detail);

export const unauthenticated = () => problem(401, 'unauthenticated', 'Sign in to continue.');

export const validation = (field: string, code: string, message: string) =>
  problem(422, 'validation_failed', message, [{ field, code, message }]);

/**
 * Brief §33 / web 01 §7.1 rule 5: payments, AI, live location sharing and chat delivery are
 * never simulated. Their endpoints answer 503 until the real backend module exists.
 */
export const notInMock = (feature: string) =>
  problem(
    503,
    'feature_not_available_in_mock',
    `${feature} requires the live platform service and is intentionally not simulated by the mock adapter.`,
  );
