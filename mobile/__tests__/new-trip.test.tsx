// req: TRIP-001
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { i18n } from '@/i18n';

import NewTrip from '../app/trips/new';

const mockApi = { get: jest.fn(), post: jest.fn(), newIdempotencyKey: jest.fn(() => 'key-1') };
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ useRouter: () => mockRouter, Stack: { Screen: () => null } }));

const lisbon = {
  id: 'd-lisbon',
  kind: 'city',
  slug: 'lisbon-pt',
  path: 'portugal/lisbon',
  name: 'Lisbon',
  country_code: 'PT',
  country_name: 'Portugal',
  continent: 'europe',
  tagline: null,
  cover: null,
};

async function renderScreen() {
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
      <QueryClientProvider client={client}>
        <NewTrip />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  jest.clearAllMocks();
  await i18n.changeLanguage('en');
});

it('creates a trip by hand and opens it in the editor', async () => {
  mockApi.get.mockResolvedValue({ data: [lisbon], page: { next_cursor: null, has_more: false } });
  mockApi.post.mockResolvedValue({ id: 't1' });
  await renderScreen();
  expect(screen.getByTestId('new-trip-create')).toBeDisabled();

  await fireEvent.changeText(screen.getByTestId('new-trip-destination'), 'lis');
  await fireEvent.press(await screen.findByText('Lisbon, Portugal'));
  await fireEvent.changeText(screen.getByTestId('new-trip-start'), '2026-12-04');
  await fireEvent.changeText(screen.getByTestId('new-trip-end'), '2026-12-01');
  expect(screen.getByTestId('new-trip-create')).toBeDisabled(); // last day before the first
  await fireEvent.changeText(screen.getByTestId('new-trip-end'), '2026-12-06');
  await fireEvent.press(screen.getByTestId('new-trip-create'));

  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/trips', {
      idempotencyKey: 'key-1',
      body: {
        title: 'Trip to Lisbon',
        start_date: '2026-12-04',
        end_date: '2026-12-06',
        destination_ids: ['d-lisbon'],
      },
    }),
  );
  expect(mockRouter.replace).toHaveBeenCalledWith({
    pathname: '/trips/[id]',
    params: { id: 't1' },
  });
});
