// req: DEST-003, AI-002, AI-003, TRIP-001, TRIP-003
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { AIGeneration, Place, Trip } from '@/features/explore/api';
import { i18n } from '@/i18n';

import Explore from '../app/(tabs)/explore';
import PlaceScreen from '../app/places/[id]';
import TripScreen from '../app/trips/[id]';
import Trips from '../app/trips/index';
import Plan from '../app/trips/plan';
import Review from '../app/trips/review';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Stack: { Screen: () => null },
}));
jest.mock('@/features/feed/location', () => ({
  getCoarsePosition: jest.fn(async () => ({ status: 'granted', near: '38.72,-9.14' })),
}));

async function renderUi(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, refetchInterval: false },
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

const me: Me = {
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
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: true,
};
const lisbon = {
  id: 'd-lisbon',
  kind: 'city',
  slug: 'lisbon-pt',
  path: 'portugal/lisbon',
  name: 'Lisbon',
  country_code: 'PT',
  country_name: 'Portugal',
};
const tower = {
  id: 'p-tower',
  name: 'Belém Tower',
  category: 'attraction' as const,
  destination_id: 'd-lisbon',
  location: { lat: 38.69, lng: -9.21 },
};
const page = <T,>(data: T[]) => ({ data, page: { next_cursor: null, has_more: false } });

function place(overrides: Partial<Place> = {}): Place {
  return {
    ...tower,
    address: { line1: 'Av. Brasília', locality: 'Lisboa' },
    attributes: { opening_hours: 'Tu-Su 10:00-17:30', secret: 'x' },
    data_freshness_at: '2026-11-01T00:00:00Z',
    data_stale: false,
    attribution: {
      provider: 'osm',
      license: 'ODbL-1.0',
      text: '© OpenStreetMap contributors',
      url: null,
    },
    status: 'active',
    ...overrides,
  };
}

function generation(overrides: Partial<AIGeneration> = {}): AIGeneration {
  return {
    id: 'gen-1',
    feature: 'itinerary_generate',
    status: 'succeeded',
    created_at: '2026-11-10T00:00:00Z',
    completed_at: '2026-11-10T00:01:00Z',
    error: null,
    quota: { limit: 5, used: 1, resets_at: null },
    result: {
      itinerary: {
        destination: lisbon,
        start_date: '2026-12-04',
        end_date: '2026-12-04',
        time_zone: 'Europe/Lisbon',
        sources: [],
        days: [
          {
            day_index: 0,
            date: '2026-12-04',
            theme: 'Old town',
            items: [
              {
                kind: 'activity',
                title: 'Tower visit',
                description: 'Riverside landmark.',
                place_id: 'p-tower',
                unverified: false,
                suggested_start_time: '09:00',
                estimated_duration_minutes: 90,
                confidence: 0.9,
                rationale: 'Iconic.',
                place: tower,
                source_attribution: [{ kind: 'catalog_place' }],
              },
              {
                kind: 'meal',
                title: 'Seafood lunch',
                description: '',
                place_id: null,
                unverified: true,
                suggested_start_time: '12:30',
                estimated_duration_minutes: 60,
                confidence: 0.5,
                rationale: 'Local food.',
                place: null,
                source_attribution: [{ kind: 'ai_general_knowledge' }],
              },
            ],
          },
        ],
      },
      warnings: ['Check opening hours before you go.'],
      disclaimer: 'AI suggestions can be wrong or out of date.',
      confidence: 0.7,
    },
    ...overrides,
  };
}

const trip: Trip = {
  id: 't1',
  title: 'Trip to Lisbon',
  start_date: '2026-12-04',
  end_date: '2026-12-04',
  status: 'planning',
  origin: 'ai_assisted',
  destinations: [{ destination: lisbon }],
  days: [
    {
      id: 'day-1',
      day_index: 0,
      date: '2026-12-04',
      items: [
        {
          id: 'i1',
          kind: 'activity',
          title: 'Tower visit',
          notes: null,
          start_time: '09:00',
          duration_minutes: 90,
          origin: 'ai',
          unverified: false,
          place: tower,
        },
      ],
    },
  ],
  version: 2,
};

beforeEach(async () => {
  jest.clearAllMocks();
  for (const fn of [mockApi.get, mockApi.post, mockApi.put, mockApi.patch, mockApi.delete]) {
    fn.mockReset(); // drop unconsumed one-off responses too
  }
  mockParams = {};
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

describe('explore', () => {
  it('asks guests to sign in before planning', async () => {
    useSessionStore.getState().setSignedOut();
    await renderUi(<Explore />);
    expect(screen.getByText('Sign in to plan trips and see places.')).toBeTruthy();
    expect(screen.queryByTestId('explore-plan')).toBeNull();
  });

  it('lists places in a chosen destination, searches them and opens one', async () => {
    mockApi.get.mockImplementation(async (path: string, options?: { query?: { q?: string } }) => {
      if (path === '/v1/destinations/search') return page([lisbon]);
      if (path === '/v1/destinations/d-lisbon')
        return { ...lisbon, centroid: { lat: 38.7223, lng: -9.1393 }, time_zone: 'Europe/Lisbon' };
      if (path === '/v1/places/nearby') return page([tower]);
      if (path === '/v1/places/search') return page(options?.query?.q === 'zzz' ? [] : [tower]);
      throw new Error(path);
    });
    await renderUi(<Explore />);
    await fireEvent.changeText(screen.getByTestId('explore-destination'), 'lis');
    await fireEvent.press(await screen.findByTestId('explore-destination-lisbon-pt'));
    expect(await screen.findByText('Belém Tower')).toBeTruthy();
    expect(screen.getByText('Attraction')).toBeTruthy();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/places/nearby', {
      query: { near: '38.722,-9.139', radius_m: 5000, limit: 30 },
    });

    await fireEvent.changeText(screen.getByTestId('explore-search'), 'zzz');
    expect(await screen.findByText('No places found here yet.')).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('explore-search'), 'bel');
    await fireEvent.press(await screen.findByTestId('place-p-tower'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/places/[id]',
      params: { id: 'p-tower' },
    });
    await fireEvent.press(screen.getByTestId('explore-plan'));
    expect(mockRouter.push).toHaveBeenCalledWith('/trips/plan');
  });

  it('shows places near the device position', async () => {
    mockApi.get.mockResolvedValue(page([tower]));
    await renderUi(<Explore />);
    await fireEvent.press(screen.getByTestId('explore-near-me'));
    expect(await screen.findByText('Belém Tower')).toBeTruthy();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/places/nearby', {
      query: { near: '38.72,-9.14', radius_m: 5000, limit: 30 },
    });
  });
});

describe('place detail', () => {
  it('shows licensed details with source and freshness, and saves the place', async () => {
    mockParams = { id: 'p-tower' };
    let saved = false;
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/places/p-tower'
        ? place({ data_stale: true })
        : page(saved ? [{ place: tower, collection: 'default', note: null, created_at: 'x' }] : []),
    );
    mockApi.put.mockImplementation(async () => {
      saved = true;
      return {};
    });
    mockApi.delete.mockImplementation(async () => {
      saved = false;
    });
    await renderUi(<PlaceScreen />);
    expect(await screen.findByText('Opening hours: Tu-Su 10:00-17:30')).toBeTruthy();
    expect(screen.queryByText(/secret/)).toBeNull(); // only known attributes are shown
    expect(screen.getByText('Source: © OpenStreetMap contributors')).toBeTruthy();
    expect(screen.getByText('These details may be out of date. Check before you go.')).toBeTruthy();
    expect(screen.getByText('Av. Brasília, Lisboa')).toBeTruthy();

    await waitFor(() => expect(screen.getByTestId('place-save')).toBeEnabled());
    await fireEvent.press(screen.getByTestId('place-save'));
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/users/me/saved-places/p-tower', { body: {} }),
    );
    expect(await screen.findByText('Remove from saved')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('place-save'));
    await waitFor(() =>
      expect(mockApi.delete).toHaveBeenCalledWith('/v1/users/me/saved-places/p-tower'),
    );
  });
});

describe('AI planner', () => {
  async function fill() {
    mockApi.get.mockResolvedValue(page([lisbon]));
    await renderUi(<Plan />);
    await fireEvent.changeText(screen.getByTestId('plan-destination'), 'lis');
    await fireEvent.press(await screen.findByTestId('plan-destination-lisbon-pt'));
    await fireEvent.changeText(screen.getByTestId('plan-start'), '2026-12-04');
    await fireEvent.changeText(screen.getByTestId('plan-end'), '2026-12-06');
    await fireEvent.changeText(screen.getByTestId('plan-interests'), 'food, viewpoints, food');
    await fireEvent.press(screen.getByTestId('plan-pace-relaxed'));
  }

  it('sends trip parameters only and opens the review', async () => {
    mockApi.post.mockResolvedValue(generation({ status: 'pending', result: null }));
    await fill();
    await fireEvent.press(screen.getByTestId('plan-generate'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/ai/itineraries/generate', {
        idempotencyKey: 'key-1',
        body: {
          destination_id: 'd-lisbon',
          start_date: '2026-12-04',
          end_date: '2026-12-06',
          pace: 'relaxed',
          interests: ['food', 'viewpoints'],
        },
      }),
    );
    expect(mockRouter.replace).toHaveBeenCalledWith({
      pathname: '/trips/review',
      params: { generation: 'gen-1' },
    });
  });

  it('explains an exhausted monthly quota and rejects bad dates', async () => {
    mockApi.post.mockRejectedValue(
      new ApiProblem(
        { status: 409, code: 'quota_exceeded', title: 'Conflict', type: 'x' },
        'req-1',
      ),
    );
    await fill();
    await fireEvent.press(screen.getByTestId('plan-generate'));
    expect(
      await screen.findByText("You've used this month's AI plans. Premium includes more."),
    ).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('plan-end'), '2026-12-01');
    expect(screen.getByTestId('plan-generate')).toBeDisabled();
  });
});

describe('itinerary review', () => {
  it('shows the plan with its disclaimer and saves it as a trip', async () => {
    mockParams = { generation: 'gen-1' };
    mockApi.get.mockResolvedValue(generation());
    mockApi.post.mockImplementation(async (path: string) =>
      path === '/v1/trips' ? { ...trip, version: 1 } : trip,
    );
    await renderUi(<Review />);
    expect(await screen.findByText('AI suggestions can be wrong or out of date.')).toBeTruthy();
    expect(screen.getByText('Day 1 · 2026-12-04')).toBeTruthy();
    expect(screen.getByText('09:00 · Tower visit')).toBeTruthy();
    expect(screen.getByText('Belém Tower')).toBeTruthy();
    expect(screen.getByText('Unverified suggestion')).toBeTruthy();
    expect(screen.getByText('Check opening hours before you go.')).toBeTruthy();

    await fireEvent.press(screen.getByTestId('review-save'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/trips/t1/apply-itinerary', {
        body: { generation_id: 'gen-1', mode: 'replace' },
        ifMatchVersion: 1,
      }),
    );
    expect(mockApi.post).toHaveBeenCalledWith('/v1/trips', {
      idempotencyKey: 'key-1',
      body: {
        title: 'Trip to Lisbon',
        start_date: '2026-12-04',
        end_date: '2026-12-04',
        destination_ids: ['d-lisbon'],
      },
    });
    expect(mockRouter.replace).toHaveBeenCalledWith({
      pathname: '/trips/[id]',
      params: { id: 't1' },
    });
  });

  it('waits while the plan is being made', async () => {
    mockParams = { generation: 'gen-1' };
    mockApi.get.mockResolvedValue(generation({ status: 'pending', result: null }));
    await renderUi(<Review />);
    expect(await screen.findByText('Planning your trip… This can take a minute.')).toBeTruthy();
  });

  it('explains a failed plan', async () => {
    mockParams = { generation: 'gen-1' };
    mockApi.get.mockResolvedValue(
      generation({ status: 'failed', result: null, error: { code: 'ai_unavailable' } }),
    );
    await renderUi(<Review />);
    expect(
      await screen.findByText("The travel assistant isn't available right now. Try again later."),
    ).toBeTruthy();
  });
});

describe('trips', () => {
  it('lists trips and shows a trip with its places', async () => {
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/trips'
        ? page([
            {
              id: 't1',
              title: 'Trip to Lisbon',
              start_date: '2026-12-04',
              end_date: '2026-12-04',
              status: 'planning',
              origin: 'ai_assisted',
              destinations: [lisbon],
              role: 'owner',
            },
          ])
        : trip,
    );
    await renderUi(<Trips />);
    await fireEvent.press(await screen.findByTestId('trip-t1'));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/trips/[id]', params: { id: 't1' } });

    mockParams = { id: 't1' };
    await renderUi(<TripScreen />);
    expect(await screen.findByText('Belém Tower · AI suggestion')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('trip-item-i1'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/places/[id]',
      params: { id: 'p-tower' },
    });
  });
});
