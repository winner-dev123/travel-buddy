/**
 * Maps BFF/platform/IdP error codes (problem `code`, or `?error=` on the login page) to message keys
 * under `auth.errors`. Unknown codes fall back to a generic message, so provider text is never shown.
 */
const KEYS = {
  invalid_credentials: 'invalidCredentials',
  email_not_confirmed: 'emailNotConfirmed',
  rate_limited: 'rateLimited',
  signup_disabled: 'signupDisabled',
  conflict: 'conflict',
  weak_password: 'weakPassword',
  same_password: 'samePassword',
  link_expired: 'linkExpired',
  link_invalid: 'linkInvalid',
  cancelled: 'cancelled',
  email_unverified: 'emailUnverified',
  account_suspended: 'accountSuspended',
  account_deleted: 'accountDeleted',
  age_restricted: 'ageRestricted',
  consent_required: 'consentRequired',
  mfa_required: 'mfa',
  identity_rejected: 'identityRejected',
  provider_unavailable: 'providerUnavailable',
} as const;

export type AuthErrorKey = (typeof KEYS)[keyof typeof KEYS] | 'generic';

export function authErrorKey(code: string | null | undefined): AuthErrorKey {
  return (code && (KEYS as Record<string, AuthErrorKey>)[code]) || 'generic';
}
