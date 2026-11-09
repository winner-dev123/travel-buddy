import { ApiClient } from '@/api';
import { assertPublishableKey, ConfigurationError } from '@/config/env';

import { exchangeIdToken, register, restoreSession, signOut } from '../session';
import { useSessionStore } from '../sessionStore';
import { SupabaseAuthClient, SupabaseAuthError } from '../supabaseAuth';
import { tokenStore } from '../tokenStore';

jest.mock('expo-crypto', () => ({ randomUUID: () => '0b8c2f4e-5d6a-4b7c-8e9f-0a1b2c3d4e5f' }));

const ME = {
  account: {
    id: 'u1',
    email: 'ana@example.com',
    email_verified: true,
    status: 'active',
    primary_locale: 'en',
  },
  profile: {
    id: 'u1',
    handle: 'ana.souza',
    display_name: 'Ana Souza',
    bio: null,
    account_visibility: 'public',
  },
  preferences: { ui_locale: 'en', time_zone: 'UTC' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: false,
};
const TOKENS = {
  token_type: 'Bearer',
  access_token: 'access-1',
  access_token_expires_at: '2026-11-09T12:15:00Z',
  refresh_token: 'refresh-1',
  refresh_token_expires_at: '2026-12-09T12:00:00Z',
  session_id: 's1',
};

function json(status: number, body: unknown, contentType = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': contentType } });
}

function problem(status: number, code: string): Response {
  return json(
    status,
    { type: `https://errors.travelbuddy.app/${code}`, title: code, status, code },
    'application/problem+json',
  );
}

function client(handler: (url: string, init: RequestInit) => Response): {
  api: ApiClient;
  calls: { url: string; init: RequestInit }[];
} {
  const calls: { url: string; init: RequestInit }[] = [];
  const api = new ApiClient({
    baseUrl: 'https://api.test',
    getAccessToken: () => tokenStore.getAccessToken(),
    getLocale: () => 'en',
    generateId: () => '00000000-0000-4000-8000-000000000000',
    fetchImpl: async (input, init) => {
      const url = String(input);
      calls.push({ url, init: init ?? {} });
      return handler(url, init ?? {});
    },
  });
  return { api, calls };
}

beforeEach(async () => {
  await tokenStore.clear();
  useSessionStore.getState().setSignedOut();
});

describe('Supabase Auth client', () => {
  const config = { url: 'https://proj.supabase.co', publishableKey: 'sb_publishable_test' };

  it('signs in with the publishable key and returns the access token', async () => {
    const fetchImpl = jest.fn(async () => json(200, { access_token: 'sb-jwt' }));
    const auth = new SupabaseAuthClient(config, fetchImpl);
    await expect(auth.signInWithPassword('ana@example.com', 'pw')).resolves.toBe('sb-jwt');
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://proj.supabase.co/auth/v1/token?grant_type=password');
    expect((init.headers as Record<string, string>).apikey).toBe('sb_publishable_test');
  });

  it.each([
    [
      400,
      { error_code: 'invalid_credentials', msg: 'Invalid login credentials' },
      'invalid_credentials',
    ],
    [400, { error_code: 'email_not_confirmed' }, 'email_not_confirmed'],
    [429, {}, 'rate_limited'],
    [500, {}, 'unknown'],
  ])('maps HTTP %s errors', async (status, body, code) => {
    const auth = new SupabaseAuthClient(config, async () => json(status, body));
    await expect(auth.signInWithPassword('a@b.co', 'x')).rejects.toMatchObject({ code });
  });

  it('reports network failures', async () => {
    const auth = new SupabaseAuthClient(config, async () => {
      throw new TypeError('Network request failed');
    });
    await expect(auth.signInWithPassword('a@b.co', 'x')).rejects.toBeInstanceOf(SupabaseAuthError);
  });

  it('treats sign-up without a session as "confirmation sent"', async () => {
    const auth = new SupabaseAuthClient(config, async () =>
      json(200, { id: 'u', email: 'a@b.co' }),
    );
    await expect(auth.signUp('a@b.co', 'longpassword')).resolves.toEqual({
      kind: 'confirmation_sent',
    });
  });
});

describe('publishable key guard', () => {
  it('accepts publishable keys and refuses secret keys', () => {
    expect(assertPublishableKey(' sb_publishable_abc ')).toBe('sb_publishable_abc');
    expect(() => assertPublishableKey('sb_secret_abc')).toThrow(ConfigurationError);
    const payload = btoa(JSON.stringify({ role: 'service_role' }));
    expect(() => assertPublishableKey(`x.${payload}.y`)).toThrow(ConfigurationError);
  });
});

describe('platform session', () => {
  it('signs in an existing user and stores the refresh token only in secure storage', async () => {
    const { api, calls } = client(() =>
      json(200, { tokens: TOKENS, user: ME, is_new_user: false }),
    );
    const outcome = await exchangeIdToken(api, 'idp-token');
    expect(outcome.kind).toBe('signed_in');
    expect(tokenStore.getAccessToken()).toBe('access-1');
    await expect(tokenStore.getRefreshToken()).resolves.toBe('refresh-1');
    expect(useSessionStore.getState().status).toBe('signed_in');
    const body = JSON.parse(String(calls[0]?.init.body)) as Record<string, unknown>;
    expect(body.id_token).toBe('idp-token');
    expect(body.client).toBe('ios');
  });

  it('asks for registration when the identity is unknown, then registers', async () => {
    let call = 0;
    const { api, calls } = client(() => {
      call += 1;
      return call === 1
        ? problem(404, 'not_found')
        : json(201, { tokens: TOKENS, user: ME, is_new_user: true });
    });
    await expect(exchangeIdToken(api, 'idp-token')).resolves.toEqual({
      kind: 'registration_required',
    });
    expect(useSessionStore.getState().pendingIdToken).toBe('idp-token');

    await register(api, {
      birthDate: '1995-05-17',
      legal: { terms_version: 'v1', privacy_version: 'v2', terms_url: '', privacy_url: '' },
      locale: 'en',
    });
    const registration = calls[1];
    expect(registration?.url).toBe('https://api.test/v1/auth/register');
    expect((registration?.init.headers as Record<string, string>)['Idempotency-Key']).toBeTruthy();
    const body = JSON.parse(String(registration?.init.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      id_token: 'idp-token',
      birth_date: '1995-05-17',
      accepted_terms_version: 'v1',
      accepted_privacy_version: 'v2',
    });
    expect(useSessionStore.getState().pendingIdToken).toBeNull();
  });

  it('restores a session from the refresh token at launch', async () => {
    await tokenStore.setRefreshToken('stored-refresh');
    const { api } = client((url) =>
      url.endsWith('/v1/auth/refresh')
        ? json(200, { ...TOKENS, refresh_token: 'rotated' })
        : json(200, ME),
    );
    await restoreSession(api);
    expect(useSessionStore.getState().status).toBe('signed_in');
    await expect(tokenStore.getRefreshToken()).resolves.toBe('rotated');
  });

  it('forgets a revoked refresh token', async () => {
    await tokenStore.setRefreshToken('revoked');
    const { api } = client(() => problem(401, 'session_revoked'));
    await restoreSession(api);
    expect(useSessionStore.getState().status).toBe('signed_out');
    await expect(tokenStore.getRefreshToken()).resolves.toBeNull();
  });

  it('signs out locally even when the server call fails', async () => {
    tokenStore.setAccessToken('access-1');
    await tokenStore.setRefreshToken('refresh-1');
    const { api } = client(() => problem(500, 'internal_error'));
    await signOut(api);
    expect(tokenStore.getAccessToken()).toBeNull();
    await expect(tokenStore.getRefreshToken()).resolves.toBeNull();
    expect(useSessionStore.getState().status).toBe('signed_out');
  });
});

describe('device id', () => {
  it('survives an undecryptable keystore entry', async () => {
    const SecureStore = jest.requireMock<{ getItemAsync: jest.Mock }>('expo-secure-store');
    SecureStore.getItemAsync.mockRejectedValueOnce(new Error('Keystore operation failed'));
    let fresh: typeof import('../session') | undefined;
    jest.isolateModules(() => {
      fresh = jest.requireActual<typeof import('../session')>('../session');
    });
    const id = await fresh!.getDeviceId();
    expect(id).toBe('0b8c2f4e-5d6a-4b7c-8e9f-0a1b2c3d4e5f');
    await expect(fresh!.getDeviceId()).resolves.toBe(id);
  });
});
