// req: PROF-001, PROF-002, I18N-001
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { i18n } from '@/i18n';
import { useSettingsStore } from '@/state/settingsStore';

import Onboarding from '../app/(onboarding)/onboarding';

/** The "Where to?" field opens the full-screen search; type, then pick a result (ADR-0035). */
async function pickDestination(testID: string, text: string, slug: string) {
  await fireEvent.press(await screen.findByTestId(testID));
  await fireEvent.changeText(await screen.findByTestId(`${testID}-input`), text);
  await fireEvent.press(await screen.findByTestId(`${testID}-${slug}`));
}

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));

const me = {
  account: {
    id: 'u9',
    email: 'me@example.com',
    email_verified: true,
    status: 'active',
    primary_locale: 'en',
  },
  profile: {
    id: 'u9',
    handle: 'traveler4821',
    display_name: 'Traveler',
    bio: null,
    account_visibility: 'public',
  },
  preferences: { ui_locale: 'en', time_zone: 'UTC' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: false,
} as Me;

const lisbon = {
  id: 'd-lisbon',
  kind: 'city',
  slug: 'lisbon-pt',
  path: 'portugal/lisbon',
  name: 'Lisbon',
  country_code: 'PT',
  country_name: 'Portugal',
};

async function renderWizard() {
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
        <Onboarding />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  jest.clearAllMocks();
  useSettingsStore.getState().setLocaleOverride(null);
  await i18n.changeLanguage('en');
  useSessionStore.getState().setSignedIn(me);
  mockApi.patch.mockImplementation(
    async (path: string, options: { body: Record<string, unknown> }) =>
      path === '/v1/users/me' ? { ...me, profile: { ...me.profile, ...options.body } } : {},
  );
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/destinations/suggest'
      ? {
          data: [{ type: 'destination', destination: lisbon }],
          page: { next_cursor: null, has_more: false },
        }
      : { ...me, onboarding_completed: true },
  );
  mockApi.put.mockResolvedValue({});
  mockApi.post.mockResolvedValue(undefined);
});

afterAll(async () => {
  useSettingsStore.getState().setLocaleOverride(null);
  await i18n.changeLanguage('en');
});

describe('onboarding wizard', () => {
  it('walks through profile, language, interests and destination, then lands on the feed', async () => {
    await renderWizard();
    expect(screen.getByTestId('onboarding-progress')).toHaveTextContent('Step 1 of 4');
    await fireEvent.changeText(screen.getByTestId('onboarding-display-name'), 'Ana Souza');
    await fireEvent.press(screen.getByTestId('onboarding-next'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me', {
        body: { display_name: 'Ana Souza' },
      }),
    );

    expect(await screen.findByTestId('onboarding-language')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('onboarding-language-pt-BR'));
    expect(await screen.findByText('Escolha seu idioma')).toBeTruthy();
    expect(useSettingsStore.getState().localeOverride).toBe('pt-BR');
    await fireEvent.press(screen.getByTestId('onboarding-next'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me/preferences', {
        body: { ui_locale: 'pt-BR' },
      }),
    );

    expect(await screen.findByTestId('onboarding-interests')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('onboarding-interest-food'));
    await fireEvent.press(screen.getByTestId('onboarding-interest-hiking'));
    await fireEvent.press(screen.getByTestId('onboarding-next'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me', {
        body: { interests: ['food', 'hiking'] },
      }),
    );

    expect(await screen.findByTestId('onboarding-destination')).toBeTruthy();
    await pickDestination('onboarding-place', 'lis', 'lisbon-pt');
    await fireEvent.press(screen.getByTestId('onboarding-next'));
    await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/'));
    expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/browse-destination', {
      body: { destination_id: 'd-lisbon' },
    });
    expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/onboarding/complete');
    expect(useSessionStore.getState().me?.onboarding_completed).toBe(true);
  });

  it('lets optional steps be skipped without saving them', async () => {
    await renderWizard();
    await fireEvent.press(screen.getByTestId('onboarding-next'));
    await fireEvent.press(await screen.findByTestId('onboarding-next')); // language: keep English
    await fireEvent.press(await screen.findByTestId('onboarding-skip')); // interests
    await fireEvent.press(await screen.findByTestId('onboarding-skip')); // destination
    await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith('/'));
    expect(mockApi.put).not.toHaveBeenCalled();
    expect(mockApi.patch).not.toHaveBeenCalledWith(
      '/v1/users/me',
      expect.objectContaining({ body: expect.objectContaining({ interests: expect.anything() }) }),
    );
    expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/onboarding/complete');
  });
});
