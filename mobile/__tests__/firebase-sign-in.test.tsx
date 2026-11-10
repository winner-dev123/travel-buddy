// req: AUTH-001, AUTH-005
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { i18n } from '@/i18n';

import SignIn from '../app/(auth)/sign-in';

const mockApi = { get: jest.fn(), post: jest.fn(), newIdempotencyKey: jest.fn(() => 'k1') };
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
const mockOpenBrowser = jest.fn();
const mockExchange = jest.fn();
const mockFetch = jest.fn();

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));
jest.mock('@/config/env', () => ({
  ...jest.requireActual('@/config/env'),
  getIdentityProviderKind: () => 'firebase',
  getFirebaseConfig: () => ({ apiKey: 'AIzaSyA-test_key_0123456789abcdefghijkl' }),
}));
jest.mock('@/auth/session', () => ({
  ...jest.requireActual('@/auth/session'),
  exchangeIdToken: (...args: unknown[]) => mockExchange(...args),
}));
jest.mock('expo-web-browser', () => ({
  openAuthSessionAsync: jest.fn(),
  openBrowserAsync: (...args: unknown[]) => mockOpenBrowser(...args),
}));

function token(emailVerified: boolean): string {
  const part = (value: unknown) => globalThis.btoa(JSON.stringify(value)).replace(/=+$/, '');
  return `${part({ alg: 'RS256' })}.${part({ sub: 'u1', email_verified: emailVerified })}.sig`;
}

function firebase(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** The Identity Toolkit methods the screen called, in order. */
function methods(): string[] {
  return mockFetch.mock.calls.map(([url]) => String(url).split('/v1/')[1]?.split('?')[0] ?? '');
}

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

beforeEach(async () => {
  jest.clearAllMocks();
  await i18n.changeLanguage('en');
  globalThis.fetch = mockFetch as unknown as typeof fetch;
  mockApi.get.mockResolvedValue({
    legal: {},
    support: { email: 'support@travelbuddy.app', url: null },
    update_required: false,
    min_supported_version: '1.0.0',
    auth_providers: ['google', 'apple'],
    password_reset_url: 'https://travelbuddy.app/forgot-password',
  });
});

it('signs in with Firebase and exchanges the ID token', async () => {
  const idToken = token(true);
  mockFetch.mockResolvedValueOnce(firebase(200, { idToken }));
  mockExchange.mockResolvedValue({ kind: 'signed_in', me: { onboarding_completed: true } });
  await renderSignIn();
  await fireEvent.changeText(screen.getByTestId('sign-in-email'), 'ana@example.com');
  await fireEvent.changeText(screen.getByTestId('sign-in-password'), 'secret-pw');
  await fireEvent.press(screen.getByTestId('sign-in-submit'));

  await waitFor(() => expect(mockExchange).toHaveBeenCalledWith(mockApi, idToken));
  expect(methods()).toEqual(['accounts:signInWithPassword']);
  expect(mockRouter.replace).toHaveBeenCalled();
  // Social sign-in does not run through Firebase yet, whatever the API lists.
  expect(screen.queryByTestId('sign-in-google')).toBeNull();
});

it('offers to resend the confirmation for an unconfirmed email', async () => {
  mockFetch
    .mockResolvedValueOnce(firebase(200, { idToken: token(false) }))
    .mockResolvedValueOnce(firebase(200, { idToken: token(false) }))
    .mockResolvedValueOnce(firebase(200, {}));
  await renderSignIn();
  await fireEvent.changeText(screen.getByTestId('sign-in-email'), 'ana@example.com');
  await fireEvent.changeText(screen.getByTestId('sign-in-password'), 'secret-pw');
  await fireEvent.press(screen.getByTestId('sign-in-submit'));

  expect(await screen.findByText('Confirm your email first. We sent you a link.')).toBeTruthy();
  expect(mockExchange).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByTestId('sign-in-resend'));
  expect(await screen.findByTestId('sign-in-info')).toBeTruthy();
  expect(methods()).toEqual([
    'accounts:signInWithPassword',
    'accounts:signInWithPassword',
    'accounts:sendOobCode',
  ]);
});

it('sends the password reset email from the app instead of opening the web page', async () => {
  mockFetch.mockResolvedValueOnce(firebase(200, { email: 'ana@example.com' }));
  await renderSignIn();
  await fireEvent.press(screen.getByTestId('sign-in-forgot-password'));
  expect(screen.getByText('Enter your email first.')).toBeTruthy();
  expect(mockFetch).not.toHaveBeenCalled();

  await fireEvent.changeText(screen.getByTestId('sign-in-email'), 'ana@example.com');
  await fireEvent.press(screen.getByTestId('sign-in-forgot-password'));
  expect(
    await screen.findByText(
      'If an account exists for this email, we sent a link to reset your password.',
    ),
  ).toBeTruthy();
  expect(methods()).toEqual(['accounts:sendOobCode']);
  expect(JSON.parse(String(mockFetch.mock.calls[0]?.[1]?.body))).toEqual({
    requestType: 'PASSWORD_RESET',
    email: 'ana@example.com',
  });
  expect(mockOpenBrowser).not.toHaveBeenCalled();
});

it('creates an account and asks to confirm the email', async () => {
  mockFetch
    .mockResolvedValueOnce(firebase(200, { idToken: token(false) }))
    .mockResolvedValueOnce(firebase(200, {}));
  await renderSignIn();
  await fireEvent.press(screen.getByTestId('sign-in-switch-mode'));
  await fireEvent.changeText(screen.getByTestId('sign-in-email'), 'new@example.com');
  await fireEvent.changeText(screen.getByTestId('sign-in-password'), 'short');
  await fireEvent.press(screen.getByTestId('sign-in-submit'));
  expect(screen.getByText('Choose a stronger password.')).toBeTruthy();
  expect(mockFetch).not.toHaveBeenCalled();

  await fireEvent.changeText(screen.getByTestId('sign-in-password'), 'long-enough-pw');
  await fireEvent.press(screen.getByTestId('sign-in-submit'));
  expect(await screen.findByTestId('sign-in-info')).toBeTruthy();
  expect(methods()).toEqual(['accounts:signUp', 'accounts:sendOobCode']);
  expect(screen.getByTestId('sign-in-resend')).toBeTruthy();
});
