// req: DISC-001, DISC-002, DISC-004, DISC-006, DISC-010, DISC-012, LOC-004, LOC-010
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { AccessibilityInfo } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { DiscoverSection } from '@/features/discovery/DiscoverSection';
import { i18n } from '@/i18n';

import Consent from '../app/discovery/consent';

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

const mockWebView = jest.requireMock<{ mockInjected: string[] }>('react-native-webview');

beforeEach(async () => {
  jest.clearAllMocks();
  mockApi.get.mockReset();
  mockApi.put.mockReset();
  mockApi.post.mockReset();
  mockWebView.mockInjected.length = 0;
  mockPermission = 'granted';
  // Searches then skip the radar's minimum turn.
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(true);
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

describe('companions map', () => {
  type Pin = { id: string; name: string; lat: number; lng: number; avatarUrl: string | null };
  type Command = { type: string; center?: { lat: number; lng: number }; pins?: Pin[] };
  const commands = (): Command[] =>
    mockWebView.mockInjected.map((code) =>
      JSON.parse(code.slice(code.indexOf('apply(') + 'apply('.length, code.lastIndexOf(');'))),
    );
  const lastPins = (): Pin[] =>
    commands()
      .filter((command) => command.type === 'pins')
      .at(-1)?.pins ?? [];
  const pageSays = async (message: object) =>
    fireEvent(screen.getByTestId('companion-map'), 'message', {
      nativeEvent: { data: JSON.stringify(message) },
    });
  /** Metres between two points (equirectangular: fine at city scale). */
  const metres = (a: { lat: number; lng: number }, b: { lat: number; lng: number }) => {
    const y = (a.lat - b.lat) * 111_320;
    const x = (a.lng - b.lng) * 111_320 * Math.cos((b.lat * Math.PI) / 180);
    return Math.hypot(x, y);
  };
  const notFound = new ApiProblem(
    { type: 'x', title: 'None', status: 404, code: 'not_found' },
    'r',
  );
  const unresolvable = new ApiProblem(
    { type: 'x', title: 'Unknown', status: 422, code: 'location_unresolvable' },
    'r',
  );
  const page = (data: unknown[]) => ({ data, page: { next_cursor: null, has_more: false } });
  const helsinkiSummary = {
    id: 'd-helsinki',
    kind: 'city',
    slug: 'helsinki-fi',
    path: 'finland/helsinki',
    name: 'Helsinki',
    country_code: 'FI',
    country_name: 'Finland',
  };
  const helsinki = {
    ...helsinkiSummary,
    centroid: { lat: 60.1699, lng: 24.9384 },
    time_zone: 'Europe/Helsinki',
  };
  const kallioSummary = {
    id: 'd-kallio',
    kind: 'neighborhood',
    slug: 'kallio-helsinki-fi',
    path: 'finland/helsinki/kallio',
    name: 'Kallio',
    country_code: 'FI',
    country_name: 'Finland',
  };
  const kallio = {
    ...kallioSummary,
    centroid: { lat: 60.1841, lng: 24.9497 },
    time_zone: 'Europe/Helsinki',
  };
  const aroundHelsinki = {
    source: 'ip',
    precision: 'city',
    label: 'Helsinki, Finland',
    center: helsinki.centroid,
    destination: helsinki,
  };
  const bo = { ...card, presence: { destination: helsinkiSummary, area: null } };
  const cy = {
    ...card,
    user: {
      id: 'u3',
      handle: 'cy',
      display_name: 'Cy',
      avatar: { id: 'm1', kind: 'image', status: 'ready', url: 'https://media.example/cy.webp' },
    },
    bio_snippet: null,
    presence: { destination: helsinkiSummary, area: kallioSummary },
    relationship: 'connected',
    can_request_connection: false,
  };

  it('shows the area from the connection and invites people who are not opted in', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/approximate-location') return aroundHelsinki;
      throw new Error(path);
    });
    await renderUi(<DiscoverSection />);
    expect(screen.getByTestId('discovery-off')).toBeTruthy();
    expect(await screen.findByText('Around Helsinki, Finland')).toBeTruthy();
    expect(screen.getByText('Approximate, from your internet connection')).toBeTruthy();
    expect(screen.getByTestId('discovery-ip-credit')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('discovery-open-consent'));
    expect(mockRouter.push).toHaveBeenCalledWith('/discovery/consent');
    // Only the lookup: no discovery session is read or started before opting in.
    expect(mockApi.get.mock.calls.map(([path]) => path)).toEqual([
      '/v1/users/me/approximate-location',
    ]);
    expect(mockApi.put).not.toHaveBeenCalled();
  });

  it('searches the area and shows each traveller around the place they share', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    let current: unknown = null;
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/approximate-location') return aroundHelsinki;
      if (path === '/v1/users/me/discovery-location') {
        if (!current) throw notFound;
        return current;
      }
      if (path === '/v1/travelers/discover') return page([bo, cy]);
      if (path === '/v1/destinations/d-helsinki') return helsinki;
      if (path === '/v1/destinations/d-kallio') return kallio;
      throw new Error(path);
    });
    mockApi.put.mockImplementation(
      async (_path: string, options: { body: { visibility: string } }) => {
        current = {
          id: 's-hel',
          destination: helsinkiSummary,
          area: null,
          visibility: options.body.visibility,
          expires_at: '2026-11-12T12:00:00Z',
        };
        return current;
      },
    );
    mockApi.post.mockResolvedValue({ id: 'r1' });
    await renderUi(<DiscoverSection />);
    await pageSays({ type: 'ready' });
    expect(await screen.findByText('Around Helsinki, Finland')).toBeTruthy();
    await waitFor(() =>
      expect(commands()).toContainEqual(
        expect.objectContaining({ type: 'view', center: helsinki.centroid }),
      ),
    );
    // The lookup alone makes nobody discoverable (LOC-004).
    expect(mockApi.put).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByTestId('discovery-search-companions'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/discovery-location', {
        body: { mode: 'destination', destination_id: 'd-helsinki', visibility: 'visible' },
      }),
    );
    expect(await screen.findByText('2 travellers in Helsinki')).toBeTruthy();
    const types = commands().map((command) => command.type);
    expect(types.lastIndexOf('scan')).toBeGreaterThan(-1);
    expect(types.lastIndexOf('pins')).toBeGreaterThan(types.lastIndexOf('scan'));
    const pins = lastPins();
    expect(pins.map((pin) => pin.id).sort()).toEqual(['u2', 'u3']);
    // Pins sit around the public centre of the area each traveller shares (DISC-004, DISC-012).
    const boPin = pins.find((pin) => pin.id === 'u2')!;
    const cyPin = pins.find((pin) => pin.id === 'u3')!;
    expect(metres(boPin, helsinki.centroid)).toBeGreaterThanOrEqual(799);
    expect(metres(boPin, helsinki.centroid)).toBeLessThanOrEqual(2201);
    expect(metres(cyPin, kallio.centroid)).toBeGreaterThanOrEqual(119);
    expect(metres(cyPin, kallio.centroid)).toBeLessThanOrEqual(421);
    expect(cyPin.avatarUrl).toBe('https://media.example/cy.webp');
    expect(screen.getByTestId('discovery-map-legend')).toBeTruthy();
    expect(screen.getByText('Visible in Helsinki')).toBeTruthy();

    // A pin opens the profile; ids the map wasn't given are ignored.
    await pageSays({ type: 'open', id: 'u3' });
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/user/[id]', params: { id: 'u3' } });
    mockRouter.push.mockClear();
    await pageSays({ type: 'open', id: 'someone-else' });
    expect(mockRouter.push).not.toHaveBeenCalled();

    // The same travellers are listed below the map.
    expect(screen.getAllByText('In common: food, backpacking')).toHaveLength(2);
    expect(screen.getByTestId('traveler-u3')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('traveler-connect-u2'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/connections/requests', {
        idempotencyKey: 'key-1',
        body: { recipient_id: 'u2', context: 'discovery' },
      }),
    );
    expect(await screen.findByTestId('traveler-sent-u2')).toBeTruthy();

    // Invisible: no results, no searching.
    await fireEvent.press(screen.getByTestId('discovery-toggle-visibility'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenLastCalledWith('/v1/users/me/discovery-location', {
        body: { mode: 'destination', destination_id: 'd-helsinki', visibility: 'invisible' },
      }),
    );
    expect(
      await screen.findByText("While you're invisible, you can't see other travellers either."),
    ).toBeTruthy();
    expect(screen.queryByTestId('traveler-u2')).toBeNull();
    expect(screen.getByTestId('discovery-search-companions')).toBeDisabled();
  });

  it('offers to switch when the connection now points to another city than the shared one', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    let current: unknown = session('visible'); // still sharing Lisbon
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/approximate-location') return aroundHelsinki;
      if (path === '/v1/users/me/discovery-location') return current;
      if (path === '/v1/destinations/d-lisbon') {
        return { ...lisbon, centroid: { lat: 38.7223, lng: -9.1393 }, time_zone: 'Europe/Lisbon' };
      }
      throw new Error(path);
    });
    mockApi.put.mockImplementation(async () => {
      current = { ...session('visible'), destination: helsinkiSummary };
      return current;
    });
    await renderUi(<DiscoverSection />);
    expect(await screen.findByTestId('discovery-moved')).toHaveTextContent(
      /^Your connection says you're in Helsinki now, but you're sharing Lisbon.Switch to Helsinki$/,
    );
    await fireEvent.press(screen.getByTestId('discovery-move-here'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/discovery-location', {
        body: { mode: 'destination', destination_id: 'd-helsinki', visibility: 'visible' },
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('discovery-status')).toHaveTextContent(/^Visible in Helsinki/),
    );
    expect(screen.queryByTestId('discovery-moved')).toBeNull();
  });

  it('asks for a city when the connection says nothing, then centres on it', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    let current: unknown = null;
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/approximate-location') throw unresolvable;
      if (path === '/v1/users/me/discovery-location') {
        if (!current) throw notFound;
        return current;
      }
      if (path === '/v1/destinations/suggest')
        return page([{ type: 'destination', destination: lisbon }]);
      if (path === '/v1/destinations/d-lisbon') {
        return { ...lisbon, centroid: { lat: 38.7223, lng: -9.1393 }, time_zone: 'Europe/Lisbon' };
      }
      throw new Error(path);
    });
    mockApi.put.mockImplementation(async () => {
      current = session('visible');
      return current;
    });
    await renderUi(<DiscoverSection />);
    await pageSays({ type: 'ready' });
    expect(await screen.findByText('Choose a city to start')).toBeTruthy();
    expect(screen.getByTestId('discovery-search-companions')).toBeDisabled();
    await pickDestination('discovery-city', 'lis', 'lisbon-pt');
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/discovery-location', {
        body: { mode: 'destination', destination_id: 'd-lisbon', visibility: 'visible' },
      }),
    );
    expect(await screen.findByText('Visible in Lisbon')).toBeTruthy();
    await waitFor(() =>
      expect(commands()).toContainEqual(
        expect.objectContaining({ type: 'view', center: { lat: 38.7223, lng: -9.1393 } }),
      ),
    );
    expect(screen.getByTestId('discovery-search-companions')).toBeEnabled();
  });

  it('says when discovery does not cover the area yet', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/approximate-location') {
        return { ...aroundHelsinki, label: 'Porto, Portugal', destination: null };
      }
      throw notFound;
    });
    await renderUi(<DiscoverSection />);
    expect(
      await screen.findByText(
        "Discovery isn't available in Porto, Portugal yet. Choose a city that has it.",
      ),
    ).toBeTruthy();
    expect(screen.getByText('Around Porto, Portugal')).toBeTruthy();
    expect(screen.getByTestId('discovery-search-companions')).toBeDisabled();
    expect(screen.getByTestId('discovery-city')).toBeTruthy();
  });

  it('says when the map cannot load', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/users/me/approximate-location') return aroundHelsinki;
      throw notFound;
    });
    await renderUi(<DiscoverSection />);
    await pageSays({ type: 'ready' });
    await pageSays({ type: 'error', reason: 'timeout' });
    expect(await screen.findByTestId('discovery-map-unavailable')).toBeTruthy();
    await pageSays({ type: 'loaded' });
    await waitFor(() => expect(screen.queryByTestId('discovery-map-unavailable')).toBeNull());
  });

  it('shares only a coarse position and explains a denied permission', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    mockApi.get.mockRejectedValue(notFound);
    mockApi.put.mockResolvedValue(session('visible'));
    await renderUi(<DiscoverSection />);
    await fireEvent.press(await screen.findByTestId('discovery-share-gps'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/discovery-location', {
        body: {
          mode: 'gps',
          point: { lat: 38.722, lng: -9.139, captured_at: expect.any(String), accuracy_m: 1200 },
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
