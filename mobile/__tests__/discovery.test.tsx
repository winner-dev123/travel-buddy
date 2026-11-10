// req: DISC-001, DISC-002, DISC-006, DISC-010
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { DiscoverSection } from '@/features/discovery/DiscoverSection';
import { i18n } from '@/i18n';

import Consent from '../app/discovery/consent';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockPermission = 'granted';

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: mockPermission })),
  getLastKnownPositionAsync: jest.fn(async () => ({
    coords: { latitude: 38.72231, longitude: -9.13934, accuracy: 1200 },
    timestamp: Date.now(),
  })),
  getCurrentPositionAsync: jest.fn(),
  Accuracy: { Low: 2 },
}));

async function renderUi(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </SafeAreaProvider>,
  );
}

function me(discovery: boolean): Me {
  return {
    account: {
      id: 'u9',
      email: 'me@example.com',
      email_verified: true,
      status: 'active',
      primary_locale: 'en',
    },
    profile: {
      id: 'u9',
      handle: 'me',
      display_name: 'Me',
      bio: null,
      account_visibility: 'public',
    },
    preferences: { ui_locale: 'en', time_zone: 'UTC' },
    privacy: { discovery_enabled: discovery, search_engine_indexing: false },
    roles: [],
    onboarding_completed: true,
  };
}

const lisbon = {
  id: 'd-lisbon',
  kind: 'city',
  slug: 'lisbon-pt',
  path: 'portugal/lisbon',
  name: 'Lisbon',
  country_code: 'PT',
  country_name: 'Portugal',
};
const session = (visibility: 'visible' | 'invisible') => ({
  id: 's1',
  destination: lisbon,
  area: null,
  visibility,
  expires_at: '2026-11-10T12:00:00Z',
});
const card = {
  user: { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null },
  bio_snippet: 'Market lover',
  presence: { destination: lisbon, area: null },
  shared: { travel_styles: ['backpacking'], interests: ['food'], languages: ['en'] },
  compatibility: 'high',
  relationship: 'none',
  can_request_connection: true,
};

beforeEach(async () => {
  jest.clearAllMocks();
  mockPermission = 'granted';
  await i18n.changeLanguage('en');
});

describe('discovery consent', () => {
  it('records consent and turns discovery on only after acknowledgement', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    mockApi.post.mockResolvedValue({});
    mockApi.patch.mockResolvedValue({});
    mockApi.get.mockResolvedValue(me(true));
    await renderUi(<Consent />);
    expect(screen.getByTestId('discovery-safety-notice')).toBeTruthy();
    expect(screen.getByTestId('discovery-turn-on')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('discovery-granularity-neighborhood'));
    await fireEvent(screen.getByTestId('discovery-understand'), 'valueChange', true);
    await fireEvent.press(screen.getByTestId('discovery-turn-on'));
    await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
    expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/consents', {
      body: {
        consent_type: 'traveler_discovery',
        version: '2026-11-01',
        granted: true,
        source: 'prompt',
      },
    });
    expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me/privacy', {
      body: { discovery_enabled: true, discovery_granularity: 'neighborhood' },
    });
    expect(useSessionStore.getState().me?.privacy.discovery_enabled).toBe(true);
  });
});

describe('discover section', () => {
  it('invites people who are not opted in to the consent screen', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    await renderUi(<DiscoverSection />);
    expect(screen.getByTestId('discovery-off')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('discovery-open-consent'));
    expect(mockRouter.push).toHaveBeenCalledWith('/discovery/consent');
    expect(mockApi.get).not.toHaveBeenCalled();
  });

  it('shares a chosen city, lists travellers and sends a discovery connection request', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    let current: unknown = null;
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/discovery-location') {
        if (!current)
          throw new ApiProblem({ type: 'x', title: 'None', status: 404, code: 'not_found' }, 'r');
        return current;
      }
      if (path === '/v1/destinations/search')
        return { data: [lisbon], page: { next_cursor: null, has_more: false } };
      if (path === '/v1/travelers/discover')
        return { data: [card], page: { next_cursor: null, has_more: false } };
      throw new Error(path);
    });
    mockApi.put.mockImplementation(
      async (_path: string, options: { body: { visibility: string } }) => {
        current = session(options.body.visibility as 'visible');
        return current;
      },
    );
    mockApi.post.mockResolvedValue({ id: 'r1' });
    await renderUi(<DiscoverSection />);
    await fireEvent.changeText(await screen.findByTestId('discovery-search'), 'lis');
    await fireEvent.press(await screen.findByTestId('discovery-match-lisbon-pt'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/discovery-location', {
        body: { mode: 'destination', destination_id: 'd-lisbon', visibility: 'visible' },
      }),
    );
    expect(await screen.findByTestId('traveler-u2')).toBeTruthy();
    expect(screen.getByText('In common: food, backpacking')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('traveler-connect-u2'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/connections/requests', {
        idempotencyKey: 'key-1',
        body: { recipient_id: 'u2', context: 'discovery' },
      }),
    );
    expect(await screen.findByTestId('traveler-sent-u2')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('discovery-toggle-visibility'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenLastCalledWith('/v1/users/me/discovery-location', {
        body: { mode: 'destination', destination_id: 'd-lisbon', visibility: 'invisible' },
      }),
    );
    expect(
      await screen.findByText("While you're invisible, you can't see other travellers either."),
    ).toBeTruthy();
  });

  it('shares only a coarse position and explains a denied permission', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    mockApi.get.mockRejectedValue(
      new ApiProblem({ type: 'x', title: 'None', status: 404, code: 'not_found' }, 'r'),
    );
    mockApi.put.mockResolvedValue(session('visible'));
    await renderUi(<DiscoverSection />);
    await fireEvent.press(await screen.findByTestId('discovery-share-gps'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/discovery-location', {
        body: {
          mode: 'gps',
          point: { lat: 38.72, lng: -9.14, captured_at: expect.any(String), accuracy_m: 1200 },
          visibility: 'visible',
        },
      }),
    );
    mockPermission = 'denied';
    mockApi.put.mockClear();
    await fireEvent.press(screen.getByTestId('discovery-share-gps'));
    expect(await screen.findByText(/Allow location access/)).toBeTruthy();
    expect(mockApi.put).not.toHaveBeenCalled();
  });
});
