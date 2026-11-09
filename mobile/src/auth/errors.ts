import type { TFunction } from 'i18next';

import { ApiNetworkError, ApiProblem } from '@/api';

import { SupabaseAuthError } from './supabaseAuth';

/** A localized, user-facing message for any sign-in or registration failure. */
export function describeAuthError(error: unknown, t: TFunction): string {
  if (__DEV__) {
    console.warn('[auth]', error);
  }
  if (error instanceof SupabaseAuthError) {
    return t(`auth.errors.${error.code}`);
  }
  if (error instanceof ApiNetworkError) {
    return t('auth.errors.network');
  }
  if (error instanceof ApiProblem) {
    switch (error.code) {
      case 'age_restricted':
      case 'consent_required':
      case 'conflict':
        return t(`registration.errors.${error.code}`);
      case 'token_expired':
      case 'token_invalid':
        return t('registration.errors.expired');
      case 'rate_limited':
        return t('auth.errors.rate_limited');
      default:
        return error.detail ?? t('auth.errors.unknown');
    }
  }
  return t('auth.errors.unknown');
}
