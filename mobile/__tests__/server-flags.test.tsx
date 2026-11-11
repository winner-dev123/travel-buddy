// req: BL-6.10 — the app follows the server's feature flags
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { APP_INFO_KEY } from '@/auth/session';
import { i18n } from '@/i18n';

import Trips from '../app/trips/index';

const mockApi = { get: jest.fn(), post: jest.fn(), newIdempotencyKey: jest.fn(() => 'k1') };
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ useRouter: () => mockRouter, Stack: { Screen: () => null } }));

const TRIP = {
  id: 't1',
  title: 'Trip to Lisbon',
  start_date: '2026-12-04',
  end_date: '2026-12-06',
};

function serve(flags: Record<string, boolean> | null, trips: () => Promise<unknown>) {
  mockApi.get.mockImplementation((path: string) => {
    if (path === '/v1/client-config') {
      return flags === null
        ? Promise.reject(new Error('offline'))
        : Promise.resolve({ legal: {}, support: {}, update_required: false, feature_flags: flags });
    }
    return trips();
  });
}

async function renderTrips(warm?: Record<string, boolean>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  if (warm) {
    // The app loads client-config at start (UpdateGate), so screens usually find it cached.
    client.setQueryData(APP_INFO_KEY, { feature_flags: warm });
  }
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={client}>
        <Trips />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

function tripCalls(): number {
  return mockApi.get.mock.calls.filter(([path]) => path !== '/v1/client-config').length;
}

beforeEach(async () => {
  jest.clearAllMocks();
  await i18n.changeLanguage('en');
});

it('shows that trips are unavailable instead of loading them when the flag is off', async () => {
  serve({ trips: false, ai_itineraries: true }, async () => ({ data: [TRIP] }));
  await renderTrips({ trips: false, ai_itineraries: true });
  expect(await screen.findByText("This feature isn't available right now.")).toBeTruthy();
  expect(screen.queryByTestId('trips-new')).toBeNull();
  expect(tripCalls()).toBe(0);
});

it('hides the AI planner when only AI itineraries are off', async () => {
  serve({ trips: true, ai_itineraries: false }, async () => ({ data: [TRIP] }));
  await renderTrips();
  expect(await screen.findByText('Trip to Lisbon')).toBeTruthy();
  expect(screen.getByTestId('trips-new')).toBeTruthy();
  expect(screen.queryByText('Plan a trip with AI')).toBeNull();
});

it('explains a refused feature instead of asking to try again', async () => {
  serve({ trips: true }, async () => {
    throw new ApiProblem(
      {
        type: 'https://errors.travelbuddy.app/feature_disabled',
        title: 'Forbidden',
        status: 403,
        code: 'feature_disabled',
      },
      'req-1',
    );
  });
  await renderTrips();
  expect(await screen.findByText("This feature isn't available right now.")).toBeTruthy();
  expect(screen.queryByText(/couldn't be loaded/)).toBeNull();
});

it('keeps features visible while the server settings are unknown', async () => {
  serve(null, async () => ({ data: [TRIP] }));
  await renderTrips();
  expect(await screen.findByText('Trip to Lisbon')).toBeTruthy();
  expect(screen.getByText('Plan a trip with AI')).toBeTruthy();
});
