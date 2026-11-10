// req: AUTH-002, AUTH-003
import { Platform } from 'react-native';

import { FirebaseAuthClient } from '../firebaseAuth';
import { availableFirebaseSocial, signInWithFirebaseSocial } from '../firebaseSocial';
import { OAuthCancelled } from '../oauth';

const mockGoogle = {
  configure: jest.fn(),
  hasPlayServices: jest.fn(async () => true),
  signIn: jest.fn(),
  signOut: jest.fn(async () => null),
};
const mockApple = {
  isAvailableAsync: jest.fn(async () => true),
  signInAsync: jest.fn(),
  AppleAuthenticationScope: { FULL_NAME: 0, EMAIL: 1 },
};

jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: mockGoogle,
  isSuccessResponse: (response: { type: string }) => response.type === 'success',
  isErrorWithCode: (error: unknown) =>
    typeof error === 'object' && error !== null && 'code' in error,
  statusCodes: { SIGN_IN_CANCELLED: 'SIGN_IN_CANCELLED' },
}));
jest.mock('expo-apple-authentication', () => mockApple);
jest.mock('expo-crypto', () => ({
  getRandomBytes: (n: number) => new Uint8Array(n).fill(171),
  digestStringAsync: async (_alg: string, value: string) => `sha256(${value})`,
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
}));
jest.mock('expo-web-browser', () => ({ openAuthSessionAsync: jest.fn() }));
jest.mock('expo-linking', () => ({ createURL: (path: string) => `travelbuddy://${path}` }));

const CLIENT_ID = '1234567890-abcdef.apps.googleusercontent.com';
const config = { apiKey: 'AIzaSyA-test_key_0123456789abcdefghijkl' };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function firebase(...responses: Response[]) {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  const client = new FirebaseAuthClient(config, async (url, init) => {
    calls.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> });
    const next = responses.shift();
    if (!next) throw new Error('unexpected request');
    return next;
  });
  return { client, calls };
}

function postBody(call: { body: Record<string, unknown> }): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(String(call.body.postBody)));
}

const originalOS = Platform.OS;

beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(Platform, 'OS', { configurable: true, get: () => 'android' });
});

afterAll(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, get: () => originalOS });
});

describe('Google through Firebase', () => {
  it('exchanges the Google ID token for a Firebase ID token', async () => {
    mockGoogle.signIn.mockResolvedValue({ type: 'success', data: { idToken: 'google-jwt' } });
    const { client, calls } = firebase(json(200, { idToken: 'firebase-jwt' }));

    await expect(
      signInWithFirebaseSocial(client, 'google', { googleWebClientId: CLIENT_ID }),
    ).resolves.toBe('firebase-jwt');
    expect(mockGoogle.configure).toHaveBeenCalledWith({ webClientId: CLIENT_ID });
    expect(calls[0]?.url).toContain('/accounts:signInWithIdp?key=');
    expect(postBody(calls[0]!)).toEqual({ id_token: 'google-jwt', providerId: 'google.com' });
    expect(calls[0]?.body).toMatchObject({
      requestUri: 'http://localhost',
      returnSecureToken: true,
    });
    // The account chooser shows every time.
    expect(mockGoogle.signOut).toHaveBeenCalled();
  });

  it('treats closing the sheet as a cancellation, not an error', async () => {
    const { client, calls } = firebase();
    mockGoogle.signIn.mockResolvedValueOnce({ type: 'cancelled', data: null });
    await expect(
      signInWithFirebaseSocial(client, 'google', { googleWebClientId: CLIENT_ID }),
    ).rejects.toBeInstanceOf(OAuthCancelled);
    mockGoogle.signIn.mockRejectedValueOnce(
      Object.assign(new Error('cancelled'), { code: 'SIGN_IN_CANCELLED' }),
    );
    await expect(
      signInWithFirebaseSocial(client, 'google', { googleWebClientId: CLIENT_ID }),
    ).rejects.toBeInstanceOf(OAuthCancelled);
    expect(calls).toHaveLength(0);
  });

  it('reports an email that already signs in another way', async () => {
    mockGoogle.signIn.mockResolvedValue({ type: 'success', data: { idToken: 'google-jwt' } });
    const { client } = firebase(json(200, { needConfirmation: true, email: 'ana@example.com' }));
    await expect(
      signInWithFirebaseSocial(client, 'google', { googleWebClientId: CLIENT_ID }),
    ).rejects.toMatchObject({ code: 'account_exists' });
  });

  it('is offered only with a web client ID', async () => {
    await expect(availableFirebaseSocial({ googleWebClientId: CLIENT_ID })).resolves.toEqual([
      'google',
    ]);
    await expect(availableFirebaseSocial({ googleWebClientId: null })).resolves.toEqual([]);
    const { client } = firebase();
    await expect(
      signInWithFirebaseSocial(client, 'google', { googleWebClientId: null }),
    ).rejects.toMatchObject({ code: 'unknown' });
  });
});

describe('Apple through Firebase', () => {
  beforeEach(() => {
    Object.defineProperty(Platform, 'OS', { configurable: true, get: () => 'ios' });
  });

  it('sends the hashed nonce to Apple and the raw one to Firebase', async () => {
    mockApple.signInAsync.mockResolvedValue({ identityToken: 'apple-jwt' });
    const { client, calls } = firebase(json(200, { idToken: 'firebase-jwt' }));

    await expect(
      signInWithFirebaseSocial(client, 'apple', { googleWebClientId: null }),
    ).resolves.toBe('firebase-jwt');
    const raw = 'ab'.repeat(16);
    expect(mockApple.signInAsync).toHaveBeenCalledWith({
      requestedScopes: [0, 1],
      nonce: `sha256(${raw})`,
    });
    expect(postBody(calls[0]!)).toEqual({
      id_token: 'apple-jwt',
      providerId: 'apple.com',
      nonce: raw,
    });
  });

  it('treats a cancelled Apple sheet as a cancellation', async () => {
    mockApple.signInAsync.mockRejectedValue(
      Object.assign(new Error('canceled'), { code: 'ERR_REQUEST_CANCELED' }),
    );
    const { client } = firebase();
    await expect(
      signInWithFirebaseSocial(client, 'apple', { googleWebClientId: null }),
    ).rejects.toBeInstanceOf(OAuthCancelled);
  });

  it('is offered on iOS devices that support it, first', async () => {
    await expect(availableFirebaseSocial({ googleWebClientId: CLIENT_ID })).resolves.toEqual([
      'apple',
      'google',
    ]);
    mockApple.isAvailableAsync.mockResolvedValueOnce(false);
    await expect(availableFirebaseSocial({ googleWebClientId: null })).resolves.toEqual([]);
  });
});
