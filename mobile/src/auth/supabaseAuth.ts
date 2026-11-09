import type { SupabaseConfig } from '@/config/env';

/**
 * Supabase Auth over its REST API (ADR-0020), without the supabase-js session machinery:
 * the Supabase access token is used ONCE, as the `id_token` exchanged for a platform session,
 * and is never stored. Only Auth endpoints are called with the publishable key.
 */

export type SupabaseAuthErrorCode =
  | 'invalid_credentials'
  | 'email_not_confirmed'
  | 'weak_password'
  | 'rate_limited'
  | 'signup_disabled'
  | 'network'
  | 'unknown';

export class SupabaseAuthError extends Error {
  override name = 'SupabaseAuthError';
  constructor(
    readonly code: SupabaseAuthErrorCode,
    message: string,
  ) {
    super(message);
  }
}

export type SignUpResult =
  { kind: 'confirmation_sent' } | { kind: 'signed_in'; accessToken: string };

type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

const ERROR_MAP: Record<string, SupabaseAuthErrorCode> = {
  invalid_credentials: 'invalid_credentials',
  invalid_grant: 'invalid_credentials',
  email_not_confirmed: 'email_not_confirmed',
  weak_password: 'weak_password',
  over_request_rate_limit: 'rate_limited',
  over_email_send_rate_limit: 'rate_limited',
  signup_disabled: 'signup_disabled',
};

export class SupabaseAuthClient {
  private readonly fetchImpl: FetchLike;

  constructor(
    private readonly config: SupabaseConfig,
    fetchImpl?: FetchLike,
  ) {
    this.fetchImpl = fetchImpl ?? ((input, init) => fetch(input, init));
  }

  /** Email + password sign-in. Returns the Supabase access token (a short-lived JWT). */
  async signInWithPassword(email: string, password: string): Promise<string> {
    const body = await this.call('/auth/v1/token?grant_type=password', { email, password });
    const token = typeof body.access_token === 'string' ? body.access_token : undefined;
    if (!token) {
      throw new SupabaseAuthError('unknown', 'Sign-in returned no session.');
    }
    return token;
  }

  /**
   * Creates the Supabase user. With "Confirm email" on (our setting) there is no session until the
   * link in the email is opened. Supabase answers the same way for existing emails, so this does
   * not reveal whether an account exists.
   */
  async signUp(email: string, password: string): Promise<SignUpResult> {
    const body = await this.call('/auth/v1/signup', { email, password });
    if (typeof body.access_token === 'string') {
      return { kind: 'signed_in', accessToken: body.access_token };
    }
    return { kind: 'confirmation_sent' };
  }

  /** Ends the Supabase session after the exchange; failures are irrelevant to the user. */
  async signOut(accessToken: string): Promise<void> {
    try {
      await this.fetchImpl(`${this.config.url}/auth/v1/logout?scope=local`, {
        method: 'POST',
        headers: { apikey: this.config.publishableKey, Authorization: `Bearer ${accessToken}` },
      });
    } catch {
      // The token expires on its own within the hour.
    }
  }

  private async call(
    path: string,
    payload: Record<string, string>,
  ): Promise<Record<string, unknown>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.config.url}${path}`, {
        method: 'POST',
        headers: { apikey: this.config.publishableKey, 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (cause) {
      throw new SupabaseAuthError(
        'network',
        cause instanceof Error ? cause.message : 'Network error',
      );
    }
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      const raw = [body.error_code, body.code, body.error].find((v) => typeof v === 'string');
      const code =
        (typeof raw === 'string' && ERROR_MAP[raw]) ||
        (response.status === 429 ? 'rate_limited' : 'unknown');
      const message = [body.msg, body.message, body.error_description].find(
        (v) => typeof v === 'string',
      );
      throw new SupabaseAuthError(
        code,
        typeof message === 'string' ? message : `HTTP ${response.status}`,
      );
    }
    return body;
  }
}
