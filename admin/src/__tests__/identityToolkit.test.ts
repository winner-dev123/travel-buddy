import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  finishSecondFactor,
  IdentityError,
  otpauthUri,
  signInWithPassword,
  startTotpEnrollment,
} from '../auth/identityToolkit';

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

afterEach(() => vi.unstubAllGlobals());

describe('Firebase sign-in over REST', () => {
  it('asks for the TOTP code when the account has a second factor', async () => {
    const fetchMock = respond(200, {
      mfaPendingCredential: 'pending-1',
      mfaInfo: [{ mfaEnrollmentId: 'phone-1', phoneInfo: '+55***' }, { mfaEnrollmentId: 'totp-1', totpInfo: {} }],
    });
    vi.stubGlobal('fetch', fetchMock);
    const result = await signInWithPassword('key-1', 'ana@example.com', 'secret-pass');
    expect(result).toEqual({ kind: 'second_factor', pendingCredential: 'pending-1', enrollmentId: 'totp-1' });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=key-1');
    expect(JSON.parse(String(init.body))).toMatchObject({ email: 'ana@example.com', returnSecureToken: true });
    expect(init.credentials).toBe('omit');
  });

  it('returns the ID token when there is no second factor yet', async () => {
    vi.stubGlobal('fetch', respond(200, { idToken: 'id-1' }));
    await expect(signInWithPassword('k', 'a@b.co', 'p')).resolves.toEqual({ kind: 'signed_in', idToken: 'id-1' });
  });

  it('turns Firebase errors into codes', async () => {
    vi.stubGlobal('fetch', respond(400, { error: { message: 'TOO_MANY_ATTEMPTS_TRY_LATER : Access disabled' } }));
    const error = await signInWithPassword('k', 'a@b.co', 'p').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(IdentityError);
    expect((error as IdentityError).code).toBe('TOO_MANY_ATTEMPTS_TRY_LATER');
  });

  it('reports a network failure as NETWORK_ERROR', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('offline'))));
    await expect(signInWithPassword('k', 'a@b.co', 'p')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });

  it('finishes the second factor with the TOTP code', async () => {
    const fetchMock = respond(200, { idToken: 'mfa-id' });
    vi.stubGlobal('fetch', fetchMock);
    await expect(finishSecondFactor('k', 'pending', 'totp-1', '123456')).resolves.toBe('mfa-id');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/v2/accounts/mfaSignIn:finalize');
    expect(JSON.parse(String(init.body))).toEqual({
      mfaPendingCredential: 'pending',
      mfaEnrollmentId: 'totp-1',
      totpVerificationInfo: { verificationCode: '123456' },
    });
  });

  it('builds the authenticator URI from the enrollment', async () => {
    vi.stubGlobal(
      'fetch',
      respond(200, {
        totpSessionInfo: {
          sharedSecretKey: 'JBSWY3DPEHPK3PXP',
          sessionInfo: 's',
          verificationCodeLength: 6,
          periodSec: 30,
          hashingAlgorithm: 'SHA1',
        },
      }),
    );
    const enrollment = await startTotpEnrollment('k', 'id');
    const uri = otpauthUri('ana@example.com', enrollment);
    expect(uri.startsWith('otpauth://totp/Travel%20Buddy%20Staff%3Aana%40example.com?')).toBe(true);
    const params = new URL(uri.replace('otpauth://', 'https://')).searchParams;
    expect(params.get('secret')).toBe('JBSWY3DPEHPK3PXP');
    expect(params.get('issuer')).toBe('Travel Buddy Staff');
    expect(params.get('digits')).toBe('6');
    expect(params.get('period')).toBe('30');
  });
});
