import 'server-only';

/**
 * Minimal server-side client for Supabase Auth (GoTrue), the platform's identity provider
 * (ADR-0020). It calls only `/auth/v1/*` with the publishable key; the Data API is disabled and the
 * web never talks to it. Supabase sessions never reach the browser: the BFF exchanges the access
 * token once for platform tokens (`POST /v1/auth/login|register`) and then signs it out.
 */

export interface SupabaseAuthConfig {
  url: string;
  publishableKey: string;
}

export type OAuthProvider = 'google' | 'apple';

export interface SupabaseSession {
  accessToken: string;
  /** Epoch ms. */
  expiresAt: number;
}

export interface SupabaseAuthSettings {
  providers: Record<OAuthProvider, boolean>;
  signupDisabled: boolean;
}

/** `code` is the GoTrue error code (e.g. `invalid_credentials`, `email_not_confirmed`, `weak_password`). */
export class SupabaseAuthError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(`Supabase Auth request failed (${status} ${code})`);
    this.name = 'SupabaseAuthError';
  }
}

type Fetch = typeof fetch;

function errorCode(status: number, data: Record<string, unknown>): string {
  if (typeof data.error_code === 'string') return data.error_code;
  // Older token-endpoint shape: { error: 'invalid_grant', error_description: '...' }.
  const description = typeof data.error_description === 'string' ? data.error_description.toLowerCase() : '';
  if (description.includes('invalid login credentials')) return 'invalid_credentials';
  if (description.includes('email not confirmed')) return 'email_not_confirmed';
  if (typeof data.error === 'string') return data.error;
  if (status === 429) return 'over_request_rate_limit';
  return `http_${status}`;
}

function toSession(data: Record<string, unknown>, now: number): SupabaseSession | null {
  if (typeof data.access_token !== 'string' || data.access_token.length === 0) return null;
  const expiresAt =
    typeof data.expires_at === 'number'
      ? data.expires_at * 1000
      : now + (typeof data.expires_in === 'number' ? data.expires_in : 3600) * 1000;
  return { accessToken: data.access_token, expiresAt };
}

export function createSupabaseAuth(config: SupabaseAuthConfig, fetchImpl: Fetch = fetch, now: () => number = Date.now) {
  const base = `${config.url.replace(/\/+$/, '')}/auth/v1`;

  async function call(
    path: string,
    init: { method: 'GET' | 'POST' | 'PUT'; body?: unknown; token?: string; query?: Record<string, string>; revalidate?: number },
  ): Promise<Record<string, unknown>> {
    const url = new URL(`${base}${path}`);
    for (const [k, v] of Object.entries(init.query ?? {})) url.searchParams.set(k, v);
    let response: Response;
    try {
      response = await fetchImpl(url, {
        method: init.method,
        headers: {
          apikey: config.publishableKey,
          Accept: 'application/json',
          ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(init.token ? { Authorization: `Bearer ${init.token}` } : {}),
        },
        body: init.body === undefined ? undefined : JSON.stringify(init.body),
        signal: AbortSignal.timeout(10_000),
        ...(init.revalidate ? { next: { revalidate: init.revalidate } } : { cache: 'no-store' as const }),
      });
    } catch {
      throw new SupabaseAuthError(503, 'unavailable');
    }
    const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) throw new SupabaseAuthError(response.status, errorCode(response.status, data));
    return data;
  }

  function requireSession(data: Record<string, unknown>): SupabaseSession {
    const session = toSession(data, now());
    if (!session) throw new SupabaseAuthError(502, 'no_session');
    return session;
  }

  return {
    /** Browser redirect target that starts a Google/Apple sign-in with PKCE. */
    authorizeUrl(provider: OAuthProvider, codeChallenge: string, redirectTo: string): string {
      const url = new URL(`${base}/authorize`);
      url.searchParams.set('provider', provider);
      url.searchParams.set('redirect_to', redirectTo);
      url.searchParams.set('code_challenge', codeChallenge);
      url.searchParams.set('code_challenge_method', 's256');
      return url.toString();
    },

    /** Completes a PKCE flow (OAuth return, email confirmation or password-recovery link). */
    async exchangeCode(authCode: string, codeVerifier: string): Promise<SupabaseSession> {
      return requireSession(
        await call('/token', { method: 'POST', query: { grant_type: 'pkce' }, body: { auth_code: authCode, code_verifier: codeVerifier } }),
      );
    },

    async signInWithPassword(email: string, password: string): Promise<SupabaseSession> {
      return requireSession(await call('/token', { method: 'POST', query: { grant_type: 'password' }, body: { email, password } }));
    },

    /**
     * Creates an email/password identity. Returns a session when the project auto-confirms emails,
     * or null when a confirmation email was sent (its link returns to `redirectTo` with a PKCE code).
     */
    async signUp(input: { email: string; password: string; name: string; codeChallenge: string; redirectTo: string }): Promise<SupabaseSession | null> {
      const data = await call('/signup', {
        method: 'POST',
        query: { redirect_to: input.redirectTo },
        body: {
          email: input.email,
          password: input.password,
          data: { full_name: input.name, name: input.name },
          code_challenge: input.codeChallenge,
          code_challenge_method: 's256',
        },
      });
      return toSession(data, now());
    },

    /** Sends a password-recovery email whose link returns to `redirectTo` with a PKCE code. */
    async recover(email: string, codeChallenge: string, redirectTo: string): Promise<void> {
      await call('/recover', {
        method: 'POST',
        query: { redirect_to: redirectTo },
        body: { email, code_challenge: codeChallenge, code_challenge_method: 's256' },
      });
    },

    async updatePassword(accessToken: string, password: string): Promise<void> {
      await call('/user', { method: 'PUT', token: accessToken, body: { password } });
    },

    /** Ends the Supabase session after the exchange. Best effort: failures are ignored. */
    async signOut(accessToken: string): Promise<void> {
      await call('/logout', { method: 'POST', token: accessToken, query: { scope: 'local' } }).catch(() => undefined);
    },

    /** Public project settings: which social providers are enabled (cached for 5 minutes). */
    async settings(): Promise<SupabaseAuthSettings> {
      const data = await call('/settings', { method: 'GET', revalidate: 300 });
      const external = (data.external ?? {}) as Record<string, unknown>;
      return {
        providers: { google: external.google === true, apple: external.apple === true },
        signupDisabled: data.disable_signup === true,
      };
    },
  };
}

export type SupabaseAuth = ReturnType<typeof createSupabaseAuth>;
