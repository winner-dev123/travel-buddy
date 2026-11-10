// req: AUTH-002, AUTH-003
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import SignIn from '../app/(auth)/sign-in';

const mockApi = { get: jest.fn(), post: jest.fn(), newIdempotencyKey: jest.fn(() => 'k1') };
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
const mockOpenAuthSession = jest.fn();
const mockOpenBrowser = jest.fn();
const mockExchange = jest.fn();
const mockFetch = jest.fn();

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));
jest.mock('@/config/env', () => ({
  ...jest.requireActual('@/config/env'),
  getIdentityProviderKind: () => 'supabase',
  getSupabaseConfig: () => ({
    url: 'https://proj.supabase.co',
    publishableKey: 'sb_publishable_test',
  }),
}));
jest.mock('@/auth/session', () => ({
  ...jest.requireActual('@/auth/session'),
  exchangeIdToken: (...args: unknown[]) => mockExchange(...args),
}));
jest.mock('expo-web-browser', () => ({
  openAuthSessionAsync: (...args: unknown[]) => mockOpenAuthSession(...args),
  openBrowserAsync: (...args: unknown[]) => mockOpenBrowser(...args),
}));
jest.mock('expo-linking', () => ({ createURL: (path: string) => `travelbuddy://${path}` }));
jest.mock('expo-crypto', () => ({
  randomUUID: () => '0b8c2f4e-5d6a-4b7c-8e9f-0a1b2c3d4e5f',
  getRandomBytes: (n: number) => new Uint8Array(n).fill(7),
  digestStringAsync: async () => 'ab+c/d==',
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  CryptoEncoding: { BASE64: 'base64' },
}));

async function renderSignIn() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={client}>
        <SignIn />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

function appInfo(providers: string[]) {
  return {
    legal: {},
    support: { email: 'support@travelbuddy.app', url: null },
    update_required: false,
    min_supported_version: '1.0.0',
    auth_providers: providers,
    password_reset_url: 'https://travelbuddy.app/forgot-password',
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  globalThis.fetch = mockFetch as unknown as typeof fetch;
  mockFetch.mockResolvedValue(
    new Response(JSON.stringify({ access_token: 'sb-jwt' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
});

it('hides social sign-in until the API lists a provider', async () => {
  mockApi.get.mockResolvedValue(appInfo([]));
  await renderSignIn();
  await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
  expect(screen.queryByTestId('sign-in-google')).toBeNull();
  expect(screen.queryByTestId('sign-in-apple')).toBeNull();
});

// req: AUTH-005
it('opens the password reset page from sign-in', async () => {
  mockApi.get.mockResolvedValue(appInfo([]));
  await renderSignIn();
  await fireEvent.press(await screen.findByTestId('sign-in-forgot-password'));
  expect(mockOpenBrowser).toHaveBeenCalledWith('https://travelbuddy.app/forgot-password');
});

it('signs in with Google through the browser and a PKCE code exchange', async () => {
  mockApi.get.mockResolvedValue(appInfo(['google', 'apple']));
  mockOpenAuthSession.mockResolvedValue({
    type: 'success',
    url: 'travelbuddy://auth-callback?code=one-time-code',
  });
  mockExchange.mockResolvedValue({ kind: 'signed_in', me: { onboarding_completed: true } });
  await renderSignIn();
  expect(await screen.findByTestId('sign-in-apple')).toBeTruthy();
  await fireEvent.press(screen.getByTestId('sign-in-google'));

  await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/'));
  const [authorize, redirect] = mockOpenAuthSession.mock.calls[0] as [string, string];
  expect(authorize).toContain('https://proj.supabase.co/auth/v1/authorize?provider=google');
  expect(authorize).toContain('code_challenge=ab-c_d');
  expect(redirect).toBe('travelbuddy://auth-callback');
  const [tokenUrl, init] = mockFetch.mock.calls[0] as [string, RequestInit];
  expect(tokenUrl).toBe('https://proj.supabase.co/auth/v1/token?grant_type=pkce');
  expect(JSON.parse(init.body as string)).toEqual({
    auth_code: 'one-time-code',
    code_verifier: '07'.repeat(32),
  });
  expect(mockExchange).toHaveBeenCalledWith(mockApi, 'sb-jwt');
});

it('stays quiet when the browser is closed and explains provider errors', async () => {
  mockApi.get.mockResolvedValue(appInfo(['apple']));
  mockOpenAuthSession.mockResolvedValueOnce({ type: 'cancel' });
  await renderSignIn();
  await fireEvent.press(await screen.findByTestId('sign-in-apple'));
  await waitFor(() => expect(mockOpenAuthSession).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId('sign-in-error')).toBeNull();

  mockOpenAuthSession.mockResolvedValueOnce({
    type: 'success',
    url: 'travelbuddy://auth-callback#error=access_denied&error_description=User+cancelled',
  });
  await fireEvent.press(screen.getByTestId('sign-in-apple'));
  expect(await screen.findByTestId('sign-in-error')).toHaveTextContent(
    'Something went wrong. Please try again.',
  );
  expect(mockExchange).not.toHaveBeenCalled();
});
