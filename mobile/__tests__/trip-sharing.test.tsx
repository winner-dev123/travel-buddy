// req: TRIP-005
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Trip } from '@/features/explore/api';
import { i18n } from '@/i18n';

import TripScreen from '../app/trips/[id]';

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
  useLocalSearchParams: () => ({ id: 't1' }),
  Stack: { Screen: () => null },
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

function me(id: string): Me {
  return {
    account: {
      id,
      email: 'me@example.com',
      email_verified: true,
      status: 'active',
      primary_locale: 'en',
    },
    profile: { id, handle: 'me', display_name: 'Me', bio: null, account_visibility: 'public' },
    preferences: { ui_locale: 'en', time_zone: 'UTC' },
    privacy: { discovery_enabled: false, search_engine_indexing: false },
    roles: [],
    onboarding_completed: true,
    entitlements: { plan: 'free', features: {} },
  };
}

const person = (id: string, name: string) => ({
  id,
  handle: name.toLowerCase(),
  display_name: name,
  avatar: null,
});

function trip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 't1',
    title: 'Lisbon weekend',
    start_date: '2026-12-04',
    end_date: '2026-12-05',
    status: 'planning',
    origin: 'manual',
    destinations: [],
    days: [],
    owner: person('owner', 'Owner'),
    visibility: 'private',
    group_id: null,
    collaborators: [{ user: person('bea', 'Bea'), role: 'viewer' }],
    version: 3,
    ...overrides,
  };
}

beforeEach(async () => {
  for (const fn of [mockApi.get, mockApi.put, mockApi.patch, mockApi.delete, mockRouter.back]) {
    fn.mockReset();
  }
  await i18n.changeLanguage('en');
});

it('lets the owner change visibility and share with connections', async () => {
  useSessionStore.getState().setSignedIn(me('owner'));
  mockApi.get.mockImplementation((path: string) =>
    Promise.resolve(
      path === '/v1/trips/t1'
        ? trip()
        : {
            data: [
              { user: person('bea', 'Bea'), connected_at: '2026-01-01T00:00:00Z' },
              { user: person('caio', 'Caio'), connected_at: '2026-01-01T00:00:00Z' },
            ],
            page: { next_cursor: null },
          },
    ),
  );
  mockApi.patch.mockResolvedValueOnce(trip({ visibility: 'connections', version: 4 }));
  mockApi.put.mockResolvedValue(trip());
  await renderUi(<TripScreen />);
  await fireEvent.press(await screen.findByTestId('trip-visibility-connections'));
  await waitFor(() =>
    expect(mockApi.patch).toHaveBeenCalledWith('/v1/trips/t1', {
      body: { visibility: 'connections' },
      ifMatchVersion: 3,
    }),
  );
  // Bea is already on the trip, so only Caio can be added.
  await fireEvent.press(await screen.findByTestId('trip-add-caio'));
  expect(screen.queryByTestId('trip-add-bea')).toBeNull();
  await waitFor(() =>
    expect(mockApi.put).toHaveBeenCalledWith('/v1/trips/t1/collaborators/caio', {
      body: { role: 'viewer' },
    }),
  );
  await fireEvent.press(screen.getByTestId('trip-role-bea'));
  await waitFor(() =>
    expect(mockApi.put).toHaveBeenCalledWith('/v1/trips/t1/collaborators/bea', {
      body: { role: 'editor' },
    }),
  );
});

it('lets a collaborator leave', async () => {
  useSessionStore.getState().setSignedIn(me('bea'));
  mockApi.get.mockResolvedValue(trip());
  mockApi.delete.mockResolvedValueOnce(undefined);
  await renderUi(<TripScreen />);
  expect(screen.queryByTestId('trip-sharing')).toBeNull();
  await fireEvent.press(await screen.findByTestId('trip-leave'));
  await waitFor(() =>
    expect(mockApi.delete).toHaveBeenCalledWith('/v1/trips/t1/collaborators/bea'),
  );
  await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
});
