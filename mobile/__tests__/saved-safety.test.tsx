// req: SAFE-008, TRIP-003
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { i18n } from '@/i18n';

import SavedPlaces from '../app/saved';
import SafetyCenter from '../app/settings/safety';

const mockApi = { get: jest.fn(), delete: jest.fn() };
const mockRouter = { push: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  Stack: { Screen: () => null },
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

const saved = (id: string, name: string, collection = 'default', note: string | null = null) => ({
  place: {
    id,
    name,
    category: 'museum',
    destination_id: 'd1',
    location: { lat: 38.7, lng: -9.1 },
  },
  collection,
  note,
  created_at: '2026-11-01T10:00:00Z',
});

beforeEach(async () => {
  mockApi.get.mockReset();
  mockApi.delete.mockReset();
  mockRouter.push.mockReset();
  await i18n.changeLanguage('en');
});

describe('saved places', () => {
  it('lists saved places by collection, opens one and removes another', async () => {
    mockApi.get.mockResolvedValue({
      data: [
        saved('p1', 'Tile Museum', 'default', 'Go early'),
        saved('p2', 'Gulbenkian', 'Rainy day'),
      ],
      page: { next_cursor: null, has_more: false },
    });
    mockApi.delete.mockResolvedValue(undefined);
    await renderUi(<SavedPlaces />);

    expect(await screen.findByTestId('saved-p1')).toHaveTextContent('Tile MuseumMuseum · Go early');
    expect(screen.getByText('Rainy day')).toBeTruthy();
    expect(screen.getByText('Saved')).toBeTruthy(); // the default collection, named
    await fireEvent.press(screen.getByTestId('saved-p1'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/places/[id]',
      params: { id: 'p1' },
    });
    await fireEvent.press(screen.getByLabelText('Remove Gulbenkian from saved places'));
    await waitFor(() =>
      expect(mockApi.delete).toHaveBeenCalledWith('/v1/users/me/saved-places/p2'),
    );
    expect(mockApi.get).toHaveBeenCalledWith('/v1/users/me/saved-places', {
      query: { limit: 100 },
    });
  });

  it('explains an empty list', async () => {
    mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } });
    await renderUi(<SavedPlaces />);
    expect(await screen.findByTestId('saved-empty')).toBeTruthy();
  });
});

describe('safety center', () => {
  it('shows bundled guidance without the network and links to support', async () => {
    await renderUi(<SafetyCenter />);
    for (const section of ['meeting', 'location', 'scams', 'reporting', 'emergency']) {
      expect(screen.getByTestId(`safety-${section}`)).toBeTruthy();
    }
    expect(screen.getByTestId('safety-emergency')).toHaveTextContent(/112/);
    expect(screen.getByTestId('safety-scams')).toHaveTextContent(/Challenge prizes never cost/);
    expect(mockApi.get).not.toHaveBeenCalled(); // works offline
    await fireEvent.press(screen.getByTestId('safety-contact'));
    expect(mockRouter.push).toHaveBeenCalledWith('/settings/help');
  });

  it('is translated', async () => {
    await i18n.changeLanguage('pt-BR');
    await renderUi(<SafetyCenter />);
    expect(screen.getByTestId('safety-emergency')).toHaveTextContent(/190/);
  });
});
