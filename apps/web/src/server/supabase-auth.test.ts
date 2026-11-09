// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { parseEnv } from './env-core';
import { codeChallengeS256, newCodeVerifier, sealIdp, unsealIdp, type IdpFlow } from './idp-flow';
import { createSupabaseAuth, SupabaseAuthError } from './supabase-auth';

const SECRET = 'test-secret-that-is-at-least-thirty-two-characters';
const CONFIG = { url: 'https://example-project.supabase.co/', publishableKey: 'sb_publishable_test' };

function fakeFetch(status: number, body: unknown) {
  return vi.fn(async (_url: URL | RequestInfo, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
}

describe('PKCE (RFC 7636)', () => {
  it('derives the S256 challenge from the RFC test vector', async () => {
    // RFC 7636 Appendix B.
    expect(await codeChallengeS256('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
  });

  it('generates high-entropy, URL-safe verifiers', () => {
    const a = newCodeVerifier();
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(newCodeVerifier()).not.toBe(a);
  });
});

describe('sealed IdP cookies', () => {
  const flow: IdpFlow = { v: 'verifier-123', intent: 'signup', next: '/feed', locale: 'fr', reg: { birth_date: '1990-01-01', terms: '2026-11-01', privacy: '2026-11-01' } };

  it('round-trips without exposing the verifier or birth date', async () => {
    const sealed = await sealIdp('flow', flow, SECRET, 60);
    expect(sealed).not.toContain('verifier-123');
    expect(sealed).not.toContain('1990');
    expect(await unsealIdp('flow', sealed, SECRET)).toEqual(flow);
  });

  it('rejects another secret, a different cookie kind and tampering', async () => {
    const sealed = await sealIdp('flow', flow, SECRET, 60);
    expect(await unsealIdp('flow', sealed, `${SECRET}-other`)).toBeNull();
    expect(await unsealIdp('pending', sealed, SECRET)).toBeNull();
    expect(await unsealIdp('flow', `${sealed.slice(0, -2)}xx`, SECRET)).toBeNull();
    expect(await unsealIdp('flow', undefined, SECRET)).toBeNull();
  });

  it('expires', async () => {
    vi.useFakeTimers();
    try {
      const sealed = await sealIdp('pending', { t: 'tok', e: Date.now() + 3_600_000, kind: 'register', next: '/feed', locale: 'en' }, SECRET, 60);
      vi.setSystemTime(Date.now() + 61_000);
      expect(await unsealIdp('pending', sealed, SECRET)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('Supabase Auth client (ADR-0020)', () => {
  it('builds the PKCE authorize URL for social providers', () => {
    const auth = createSupabaseAuth(CONFIG, fakeFetch(200, {}));
    const url = new URL(auth.authorizeUrl('google', 'challenge', 'https://web.example/api/auth/callback'));
    expect(url.origin + url.pathname).toBe('https://example-project.supabase.co/auth/v1/authorize');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      provider: 'google',
      redirect_to: 'https://web.example/api/auth/callback',
      code_challenge: 'challenge',
      code_challenge_method: 's256',
    });
  });

  it('exchanges a PKCE code with only the publishable key', async () => {
    const fetchMock = fakeFetch(200, { access_token: 'sb-access', expires_at: 2_000_000_000, refresh_token: 'sb-refresh' });
    const auth = createSupabaseAuth(CONFIG, fetchMock);
    const session = await auth.exchangeCode('auth-code', 'verifier');
    expect(session).toEqual({ accessToken: 'sb-access', expiresAt: 2_000_000_000_000 });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toBe('https://example-project.supabase.co/auth/v1/token?grant_type=pkce');
    expect(init?.method).toBe('POST');
    expect(init?.headers).toMatchObject({ apikey: 'sb_publishable_test' });
    expect((init?.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(JSON.parse(String(init?.body))).toEqual({ auth_code: 'auth-code', code_verifier: 'verifier' });
  });

  it('maps both GoTrue error shapes to stable codes', async () => {
    await expect(createSupabaseAuth(CONFIG, fakeFetch(400, { code: 400, error_code: 'invalid_credentials', msg: 'Invalid login credentials' })).signInWithPassword('a@b.co', 'x')).rejects.toMatchObject({
      status: 400,
      code: 'invalid_credentials',
    });
    await expect(createSupabaseAuth(CONFIG, fakeFetch(400, { error: 'invalid_grant', error_description: 'Email not confirmed' })).signInWithPassword('a@b.co', 'x')).rejects.toMatchObject({
      code: 'email_not_confirmed',
    });
    const offline = createSupabaseAuth(CONFIG, vi.fn(async () => Promise.reject(new TypeError('fetch failed'))));
    await expect(offline.exchangeCode('c', 'v')).rejects.toBeInstanceOf(SupabaseAuthError);
  });

  it('returns no session when sign-up awaits email confirmation, and never sends the birth date', async () => {
    const fetchMock = fakeFetch(200, { id: 'user-id', email: 'a@b.co', confirmation_sent_at: '2026-11-09T12:00:00Z' });
    const auth = createSupabaseAuth(CONFIG, fetchMock);
    const result = await auth.signUp({ email: 'a@b.co', password: 'long-enough', name: 'Ana', codeChallenge: 'ch', redirectTo: 'https://web.example/api/auth/callback' });
    expect(result).toBeNull();
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(String(url)).searchParams.get('redirect_to')).toBe('https://web.example/api/auth/callback');
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({ email: 'a@b.co', code_challenge: 'ch', code_challenge_method: 's256', data: { name: 'Ana' } });
    expect(JSON.stringify(body)).not.toMatch(/birth/);
  });

  it('reads enabled social providers from the public settings', async () => {
    const auth = createSupabaseAuth(CONFIG, fakeFetch(200, { external: { google: true, apple: false, email: true }, disable_signup: false }));
    expect(await auth.settings()).toEqual({ providers: { google: true, apple: false }, signupDisabled: false });
  });

  it('signs out best-effort', async () => {
    const auth = createSupabaseAuth(CONFIG, fakeFetch(500, {}));
    await expect(auth.signOut('tok')).resolves.toBeUndefined();
  });
});

describe('environment: Supabase identity provider', () => {
  const hosted = {
    APP_ENV: 'staging',
    API_BASE_URL: 'https://api.example.com',
    SESSION_SECRET: SECRET,
    NEXT_PUBLIC_SITE_URL: 'https://web.example.com',
    NEXT_PUBLIC_MAP_STYLE_URL: 'https://maps.example.com/style.json',
  };
  const jwtKey = (role: string) => `eyJhbGciOiJIUzI1NiJ9.${Buffer.from(JSON.stringify({ role, iss: 'supabase' })).toString('base64url')}.sig`;

  it('is the default outside development and derives the redirect URI from the site URL', () => {
    const e = parseEnv({ ...hosted, SUPABASE_URL: 'https://example-project.supabase.co/', SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_abc' });
    expect(e.identityProvider).toBe('supabase');
    expect(e.supabase).toEqual({ url: 'https://example-project.supabase.co', publishableKey: 'sb_publishable_abc', redirectUri: 'https://web.example.com/api/auth/callback' });
  });

  it('requires the project URL and publishable key', () => {
    expect(() => parseEnv(hosted)).toThrow(/SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY/);
  });

  it('refuses secret and service-role keys', () => {
    expect(() => parseEnv({ ...hosted, SUPABASE_URL: 'https://p.supabase.co', SUPABASE_PUBLISHABLE_KEY: 'sb_secret_abc' })).toThrow(/never a secret/);
    expect(() => parseEnv({ ...hosted, SUPABASE_URL: 'https://p.supabase.co', SUPABASE_PUBLISHABLE_KEY: jwtKey('service_role') })).toThrow(/never a secret/);
    expect(parseEnv({ ...hosted, SUPABASE_URL: 'https://p.supabase.co', SUPABASE_PUBLISHABLE_KEY: jwtKey('anon') }).supabase?.publishableKey).toBe(jwtKey('anon'));
  });

  it('keeps the dev identity provider (and no Supabase settings) in development and demo', () => {
    expect(parseEnv({ APP_ENV: 'development' }).identityProvider).toBe('dev');
    expect(parseEnv({ APP_ENV: 'demo', SESSION_SECRET: SECRET }).supabase).toBeNull();
  });
});
