/**
 * What the sign-in screen needs from an identity provider (ADR-0020, ADR-0028). Each provider
 * returns an ID token that is used ONCE, exchanged for a platform session, and never stored.
 */

export type AuthErrorCode =
  | 'invalid_credentials'
  | 'email_not_confirmed'
  | 'weak_password'
  | 'rate_limited'
  | 'signup_disabled'
  /** The email already signs in another way (Firebase: one account per email). */
  | 'account_exists'
  | 'network'
  | 'unknown';

/** A sign-in failure reported by the identity provider; `code` picks the localized message. */
export class AuthProviderError extends Error {
  override name = 'AuthProviderError';
  constructor(
    readonly code: AuthErrorCode,
    message: string,
  ) {
    super(message);
  }
}

export type SignUpResult =
  { kind: 'confirmation_sent' } | { kind: 'signed_in'; accessToken: string };

/** The password the apps ask for; the provider may enforce more (AUTH-001). */
export const MIN_PASSWORD_LENGTH = 8;

export interface PasswordAuthClient {
  /** "Continue with Google / Apple" runs through this provider (AUTH-002, AUTH-003). */
  readonly supportsSocial: boolean;
  /** The reset email is sent from the app; otherwise the reset runs on the web (AUTH-005). */
  readonly supportsInAppReset: boolean;
  /** Email + password sign-in. Returns the ID token to exchange for a platform session. */
  signInWithPassword(email: string, password: string): Promise<string>;
  /** Creates the account. Answers the same for existing emails, so it never reveals one exists. */
  signUp(email: string, password: string): Promise<SignUpResult>;
  /** Sends the confirmation email again (some providers need the password to do so). */
  resendConfirmation(email: string, password: string): Promise<void>;
  /** Sends the reset email; quietly does nothing for unknown addresses. */
  sendPasswordReset(email: string): Promise<void>;
  /** Ends the provider's own session after the exchange; failures are irrelevant. */
  signOut(idToken: string): Promise<void>;
}
