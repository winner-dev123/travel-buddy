// req: AUTH-001, AUTH-005
import { assertFirebaseWebApiKey, ConfigurationError, resolveIdentityProvider } from '@/config/env';

import { emailVerified, FirebaseAuthClient, FirebaseAuthError } from '../firebaseAuth';
import { AuthProviderError } from '../identityClient';

const KEY = 'AIzaSyA-test_key_0123456789abcdefghijkl';
const config = { apiKey: KEY };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** An unsigned JWT-shaped token; the app only reads `email_verified`. */
function idToken(claims: Record<string, unknown>): string {
  const part = (value: unknown) =>
    globalThis
      .btoa(JSON.stringify(value))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  return `${part({ alg: 'RS256' })}.${part(claims)}.sig`;
}

const VERIFIED = idToken({ sub: 'u1', email_verified: true, name: 'Ana Ç' });
const UNVERIFIED = idToken({ sub: 'u1', email_verified: false });

function failure(message: string, status = 400): Response {
  return json(status, { error: { code: status, message } });
}

type Call = { url: string; init: RequestInit };

function recorder(...responses: Response[]) {
  const calls: Call[] = [];
  const fetchImpl = jest.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const next = responses.shift();
    if (!next) throw new Error('unexpected request');
    return next;
  });
  return { calls, fetchImpl, body: (i: number) => JSON.parse(String(calls[i]?.init.body)) };
}

describe('Firebase Auth client', () => {
  it('signs in with the Web API key and returns the ID token', async () => {
    const { calls, fetchImpl, body } = recorder(
      json(200, { idToken: VERIFIED, refreshToken: 'r' }),
    );
    const auth = new FirebaseAuthClient(config, fetchImpl, () => 'pt-BR');
    await expect(auth.signInWithPassword('ana@example.com', 'secret-pw')).resolves.toBe(VERIFIED);
    expect(calls[0]?.url).toBe(
      `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${KEY}`,
    );
    expect(body(0)).toEqual({
      email: 'ana@example.com',
      password: 'secret-pw',
      returnSecureToken: true,
    });
    expect((calls[0]?.init.headers as Record<string, string>)['X-Firebase-Locale']).toBe('pt-BR');
  });

  it('refuses an account whose email is not confirmed yet', async () => {
    const { fetchImpl } = recorder(json(200, { idToken: UNVERIFIED }));
    const auth = new FirebaseAuthClient(config, fetchImpl);
    await expect(auth.signInWithPassword('a@b.co', 'x')).rejects.toMatchObject({
      code: 'email_not_confirmed',
    });
  });

  it.each([
    ['INVALID_LOGIN_CREDENTIALS', 'invalid_credentials'],
    ['EMAIL_NOT_FOUND', 'invalid_credentials'],
    ['USER_DISABLED', 'invalid_credentials'],
    ['TOO_MANY_ATTEMPTS_TRY_LATER : Access temporarily disabled.', 'rate_limited'],
    ['WEAK_PASSWORD : Password should be at least 6 characters', 'weak_password'],
    ['OPERATION_NOT_ALLOWED', 'signup_disabled'],
    ['SOMETHING_NEW', 'unknown'],
  ])('maps %s to %s', async (message, code) => {
    const auth = new FirebaseAuthClient(config, recorder(failure(message)).fetchImpl);
    const error = await auth.signInWithPassword('a@b.co', 'x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(FirebaseAuthError);
    expect(error).toBeInstanceOf(AuthProviderError);
    expect(error).toMatchObject({ code });
  });

  it('reports a network failure', async () => {
    const auth = new FirebaseAuthClient(config, async () => {
      throw new TypeError('Network request failed');
    });
    await expect(auth.signInWithPassword('a@b.co', 'x')).rejects.toMatchObject({
      code: 'network',
    });
  });

  it('signs up and sends the confirmation email to the new account', async () => {
    const { calls, fetchImpl, body } = recorder(
      json(200, { idToken: UNVERIFIED, localId: 'u1' }),
      json(200, { email: 'ana@example.com' }),
    );
    const auth = new FirebaseAuthClient(config, fetchImpl);
    await expect(auth.signUp('ana@example.com', 'long-enough')).resolves.toEqual({
      kind: 'confirmation_sent',
    });
    expect(calls[0]?.url).toContain('/accounts:signUp?');
    expect(calls[1]?.url).toContain('/accounts:sendOobCode?');
    expect(body(1)).toEqual({ requestType: 'VERIFY_EMAIL', idToken: UNVERIFIED });
  });

  it('answers an existing email exactly like a new one', async () => {
    const { calls, fetchImpl } = recorder(failure('EMAIL_EXISTS'));
    const auth = new FirebaseAuthClient(config, fetchImpl);
    await expect(auth.signUp('taken@example.com', 'long-enough')).resolves.toEqual({
      kind: 'confirmation_sent',
    });
    expect(calls).toHaveLength(1); // no email goes to the existing account's owner
  });

  it('resends the confirmation after signing in with the password', async () => {
    const { calls, fetchImpl, body } = recorder(json(200, { idToken: UNVERIFIED }), json(200, {}));
    await new FirebaseAuthClient(config, fetchImpl).resendConfirmation('a@b.co', 'pw-123456');
    expect(calls[0]?.url).toContain('/accounts:signInWithPassword?');
    expect(body(1)).toEqual({ requestType: 'VERIFY_EMAIL', idToken: UNVERIFIED });
  });

  it('sends nothing when the email is already confirmed', async () => {
    const { calls, fetchImpl } = recorder(json(200, { idToken: VERIFIED }));
    await new FirebaseAuthClient(config, fetchImpl).resendConfirmation('a@b.co', 'pw-123456');
    expect(calls).toHaveLength(1);
  });

  it('sends the password reset email and stays silent about unknown addresses', async () => {
    const sent = recorder(json(200, { email: 'ana@example.com' }));
    await new FirebaseAuthClient(config, sent.fetchImpl).sendPasswordReset('ana@example.com');
    expect(sent.body(0)).toEqual({ requestType: 'PASSWORD_RESET', email: 'ana@example.com' });

    const unknown = recorder(failure('EMAIL_NOT_FOUND'));
    await expect(
      new FirebaseAuthClient(config, unknown.fetchImpl).sendPasswordReset('nobody@example.com'),
    ).resolves.toBeUndefined();

    const limited = recorder(failure('TOO_MANY_ATTEMPTS_TRY_LATER'));
    await expect(
      new FirebaseAuthClient(config, limited.fetchImpl).sendPasswordReset('a@b.co'),
    ).rejects.toMatchObject({ code: 'rate_limited' });
  });

  it('fails clearly when Firebase returns no token', async () => {
    const auth = new FirebaseAuthClient(config, recorder(json(200, {})).fetchImpl);
    await expect(auth.signInWithPassword('a@b.co', 'x')).rejects.toMatchObject({
      code: 'unknown',
    });
  });

  it('reads email_verified from the token payload', () => {
    expect(emailVerified(VERIFIED)).toBe(true);
    expect(emailVerified(UNVERIFIED)).toBe(false);
    expect(emailVerified('not-a-jwt')).toBe(false);
    expect(emailVerified('a.!!!.c')).toBe(false);
  });
});

describe('identity provider configuration', () => {
  it('prefers the explicit choice, then Firebase when its key is set', () => {
    expect(resolveIdentityProvider('supabase', true, false)).toBe('supabase');
    expect(resolveIdentityProvider('firebase', false, false)).toBe('firebase');
    expect(resolveIdentityProvider(undefined, true, false)).toBe('firebase');
    expect(resolveIdentityProvider('', false, false)).toBe('supabase');
    expect(resolveIdentityProvider('dev', false, true)).toBe('dev');
    expect(() => resolveIdentityProvider('dev', false, false)).toThrow(ConfigurationError);
  });

  it('accepts only a Firebase Web API key', () => {
    expect(assertFirebaseWebApiKey(` ${KEY} `)).toBe(KEY);
    expect(() => assertFirebaseWebApiKey('sb_publishable_x')).toThrow(ConfigurationError);
    expect(() =>
      assertFirebaseWebApiKey('{"type": "service_account", "private_key": "-----BEGIN"}'),
    ).toThrow(/SERVICE ACCOUNT/);
  });
});
