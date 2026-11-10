import type { FirebaseConfig } from '@/config/env';

import {
  type AuthErrorCode,
  AuthProviderError,
  type PasswordAuthClient,
  type SignUpResult,
} from './identityClient';

/**
 * Firebase Authentication over its REST API (Identity Toolkit, ADR-0028), without the Firebase SDK
 * or its session machinery: the ID token is used ONCE, exchanged for a platform session, and never
 * stored; the Firebase refresh token is discarded. The Web API key only identifies the project.
 */

export class FirebaseAuthError extends AuthProviderError {
  override name = 'FirebaseAuthError';
  constructor(
    code: AuthErrorCode,
    message: string,
    /** Identity Toolkit's own code, e.g. `EMAIL_EXISTS`. */
    readonly reason: string = '',
  ) {
    super(code, message);
  }
}

type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

const BASE_URL = 'https://identitytoolkit.googleapis.com/v1';

const ERROR_MAP: Record<string, AuthErrorCode> = {
  INVALID_LOGIN_CREDENTIALS: 'invalid_credentials',
  EMAIL_NOT_FOUND: 'invalid_credentials',
  INVALID_PASSWORD: 'invalid_credentials',
  INVALID_EMAIL: 'invalid_credentials',
  USER_DISABLED: 'invalid_credentials',
  MISSING_PASSWORD: 'invalid_credentials',
  WEAK_PASSWORD: 'weak_password',
  PASSWORD_DOES_NOT_MEET_REQUIREMENTS: 'weak_password',
  TOO_MANY_ATTEMPTS_TRY_LATER: 'rate_limited',
  QUOTA_EXCEEDED: 'rate_limited',
  OPERATION_NOT_ALLOWED: 'signup_disabled',
  ADMIN_ONLY_OPERATION: 'signup_disabled',
};

/** The `email_verified` claim of an ID token (its signature is checked by the backend). */
export function emailVerified(idToken: string): boolean {
  const payload = idToken.split('.')[1];
  if (!payload) return false;
  try {
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const claims: unknown = JSON.parse(globalThis.atob(padded));
    return (
      typeof claims === 'object' &&
      claims !== null &&
      (claims as { email_verified?: unknown }).email_verified === true
    );
  } catch {
    return false;
  }
}

export class FirebaseAuthClient implements PasswordAuthClient {
  readonly supportsSocial = false;
  readonly supportsInAppReset = true;
  private readonly fetchImpl: FetchLike;

  constructor(
    private readonly config: FirebaseConfig,
    fetchImpl?: FetchLike,
    /** Language of Firebase's emails (verification, reset). */
    private readonly getLocale: () => string = () => 'en',
  ) {
    this.fetchImpl = fetchImpl ?? ((input, init) => fetch(input, init));
  }

  async signInWithPassword(email: string, password: string): Promise<string> {
    const idToken = await this.passwordToken(email, password);
    if (!emailVerified(idToken)) {
      // Firebase signs unconfirmed accounts in; the platform needs a confirmed email (AUTH-001).
      throw new FirebaseAuthError('email_not_confirmed', 'The email is not confirmed yet.');
    }
    return idToken;
  }

  async signUp(email: string, password: string): Promise<SignUpResult> {
    let body: Record<string, unknown>;
    try {
      body = await this.call('accounts:signUp', { email, password, returnSecureToken: true });
    } catch (caught) {
      if (caught instanceof FirebaseAuthError && caught.reason === 'EMAIL_EXISTS') {
        // Same answer as a new account: sign-up must not reveal who has one.
        return { kind: 'confirmation_sent' };
      }
      throw caught;
    }
    await this.sendVerification(stringField(body, 'idToken'));
    return { kind: 'confirmation_sent' };
  }

  async resendConfirmation(email: string, password: string): Promise<void> {
    // Firebase sends the confirmation only to the signed-in account itself.
    const idToken = await this.passwordToken(email, password);
    if (!emailVerified(idToken)) {
      await this.sendVerification(idToken);
    }
  }

  async sendPasswordReset(email: string): Promise<void> {
    try {
      await this.call('accounts:sendOobCode', { requestType: 'PASSWORD_RESET', email });
    } catch (caught) {
      // Projects without email enumeration protection report unknown addresses; stay silent.
      if (caught instanceof FirebaseAuthError && caught.reason === 'EMAIL_NOT_FOUND') return;
      throw caught;
    }
  }

  async signOut(): Promise<void> {
    // No server-side session to end: the ID token expires within the hour and the refresh token
    // was never kept.
  }

  private async passwordToken(email: string, password: string): Promise<string> {
    const body = await this.call('accounts:signInWithPassword', {
      email,
      password,
      returnSecureToken: true,
    });
    return stringField(body, 'idToken');
  }

  private async sendVerification(idToken: string): Promise<void> {
    await this.call('accounts:sendOobCode', { requestType: 'VERIFY_EMAIL', idToken });
  }

  private async call(
    method: string,
    payload: Record<string, string | boolean>,
  ): Promise<Record<string, unknown>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${BASE_URL}/${method}?key=${encodeURIComponent(this.config.apiKey)}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Firebase-Locale': this.getLocale() },
          body: JSON.stringify(payload),
        },
      );
    } catch (cause) {
      throw new FirebaseAuthError(
        'network',
        cause instanceof Error ? cause.message : 'Network error',
      );
    }
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      const error = (body.error ?? {}) as { message?: unknown };
      const message = typeof error.message === 'string' ? error.message : `HTTP ${response.status}`;
      // "TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account has been temporarily disabled…"
      const reason = message.split(/[\s:]/, 1)[0] ?? '';
      const code = ERROR_MAP[reason] ?? (response.status === 429 ? 'rate_limited' : 'unknown');
      throw new FirebaseAuthError(code, message, reason);
    }
    return body;
  }
}

function stringField(body: Record<string, unknown>, key: string): string {
  const value = body[key];
  if (typeof value !== 'string' || value.length === 0) {
    throw new FirebaseAuthError('unknown', 'Sign-in returned no session.');
  }
  return value;
}
