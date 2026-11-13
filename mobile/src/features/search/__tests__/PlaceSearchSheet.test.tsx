// req: DEST-001, DEST-003, LOC-005
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { useState, type ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import type { DestinationSummary } from '@/features/feed/types';
import { i18n } from '@/i18n';

import type { Suggestion } from '../api';
import { PlaceSearchSheet } from '../PlaceSearchSheet';
import { forgetRecentSearches, MAX_RECENTS, useRecentSearches } from '../recents';

const mockApi = { get: jest.fn() };
jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
const mockPosition = jest.fn();
jest.mock('@/features/feed/location', () => ({
  ...jest.requireActual('@/features/feed/location'),
  getCoarsePosition: () => mockPosition(),
}));
jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts
        .map((part) => (typeof part === 'string' ? part : (part as { uri: string }).uri))
        .join('/');
    }
    get exists() {
      return files.has(this.uri);
    }
    textSync() {
      return files.get(this.uri) ?? '';
    }
    writeSync(text: string) {
      files.set(this.uri, text);
    }
    delete() {
      files.delete(this.uri);
    }
  }
  return { File, Paths: { document: { uri: 'doc' } }, mockFiles: files };
});
const { mockFiles } = jest.requireMock<{ mockFiles: Map<string, string> }>('expo-file-system');
const RECENTS = 'doc/search-recents.json';

const town = (id: string, name: string, extra: Partial<DestinationSummary> = {}) =>
  ({
    id,
    kind: 'city',
    slug: `${name.toLowerCase()}-br`,
    path: `brazil/${name.toLowerCase()}`,
    name,
    country_code: 'BR',
    country_name: 'Brazil',
    ...extra,
  }) as DestinationSummary;
const rio = town('d-rio', 'Rio', { region_name: 'Rio de Janeiro' });
const campinas = town('d-campinas', 'Campinas', { region_name: 'São Paulo' });
const cristo: Suggestion = {
  type: 'place',
  destination: rio,
  place: {
    id: 'p-cristo',
    name: 'Christ the Redeemer',
    category: 'attraction',
    destination_id: 'd-rio',
    location: { lat: -22.95, lng: -43.21 },
  },
};
const page = <T,>(data: T[]) => ({ data, page: { next_cursor: null, has_more: false } });
const fix = { near: '-22.907,-43.173', capturedAt: '2026-11-13T12:00:00.000Z', accuracyM: 35 };

async function renderUi(ui: ReactElement) {
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
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </SafeAreaProvider>,
  );
}

function Sheet({ onSelect }: { onSelect: (s: Suggestion) => void }) {
  const [open, setOpen] = useState(true);
  return open ? (
    <PlaceSearchSheet visible onClose={() => setOpen(false)} onSelect={onSelect} testID="where" />
  ) : null;
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockFiles.clear();
  useRecentSearches.setState({ items: null });
  useSessionStore.getState().setSignedIn({ id: 'u1' } as unknown as Me);
  await i18n.changeLanguage('en');
  mockApi.get.mockImplementation(async (path: string, options?: { query?: { q?: string } }) => {
    if (path === '/v1/destinations/featured') return page([rio]);
    if (path === '/v1/destinations/suggest') {
      const q = options?.query?.q ?? '';
      if (q === 'zzz') return page([]);
      if (q === 'boom')
        throw new ApiProblem({ type: 'x', title: 'x', status: 500, code: 'internal' }, 'r');
      return page<Suggestion>([cristo, { type: 'destination', destination: campinas }]);
    }
    if (path === '/v1/destinations/resolve') return campinas;
    throw new Error(path);
  });
});

describe('search sheet', () => {
  it('offers the current location and popular towns, then suggestions as you type', async () => {
    const onSelect = jest.fn();
    await renderUi(<Sheet onSelect={onSelect} />);
    expect(screen.getByTestId('where-here')).toHaveTextContent('Use my current location');
    expect(await screen.findByTestId('where-popular-rio-br')).toHaveTextContent(/Rio de Janeiro/);
    expect(screen.queryByText('Recent')).toBeNull();

    await fireEvent.changeText(screen.getByTestId('where-input'), 'c');
    expect(mockApi.get).not.toHaveBeenCalledWith('/v1/destinations/suggest', expect.anything());
    await fireEvent.changeText(screen.getByTestId('where-input'), 'cri');
    const place = await screen.findByTestId('where-place-p-cristo');
    expect(place).toHaveTextContent(/Christ the Redeemer.*Rio, Rio de Janeiro, Brazil/);
    expect(place.props.accessibilityLabel).toBe(
      'Christ the Redeemer, place to visit, Rio, Rio de Janeiro, Brazil',
    );
    expect(screen.getByTestId('where-campinas-br')).toHaveTextContent(/São Paulo, Brazil/);
    expect(mockApi.get).toHaveBeenCalledWith('/v1/destinations/suggest', {
      query: { q: 'cri', limit: 10 },
    });

    await fireEvent.press(place);
    expect(onSelect).toHaveBeenCalledWith(cristo);
    expect(screen.queryByTestId('where-input')).toBeNull(); // closed
    expect(JSON.parse(mockFiles.get(RECENTS) ?? '[]')).toEqual([cristo]);
  });

  it('shows recent choices first and forgets them on sign-out', async () => {
    useRecentSearches.getState().remember({ type: 'destination', destination: campinas });
    useRecentSearches.getState().remember(cristo);
    useRecentSearches.setState({ items: null }); // as after a restart: read back from the device
    await renderUi(<Sheet onSelect={jest.fn()} />);
    expect(await screen.findByText('Recent')).toBeTruthy();
    expect(screen.getByTestId('where-place-p-cristo')).toBeTruthy();
    expect(screen.getByTestId('where-recent-campinas-br')).toBeTruthy();
    forgetRecentSearches();
    expect(mockFiles.has(RECENTS)).toBe(false);
    expect(useRecentSearches.getState().items).toEqual([]);
  });

  it(`keeps the last ${MAX_RECENTS} distinct choices`, () => {
    for (let i = 0; i < MAX_RECENTS + 2; i += 1) {
      useRecentSearches
        .getState()
        .remember({ type: 'destination', destination: town(`d${i}`, `Town${i}`) });
    }
    useRecentSearches
      .getState()
      .remember({ type: 'destination', destination: town('d7', 'Town7') });
    const items = useRecentSearches.getState().items ?? [];
    expect(items).toHaveLength(MAX_RECENTS);
    expect(items[0]?.destination.id).toBe('d7');
    expect(new Set(items.map((item) => item.destination.id)).size).toBe(MAX_RECENTS);
  });

  it('uses where the device is, once', async () => {
    mockPosition.mockResolvedValue({ status: 'granted', near: fix.near, fix });
    const onSelect = jest.fn();
    await renderUi(<Sheet onSelect={onSelect} />);
    await fireEvent.press(screen.getByTestId('where-here'));
    await waitFor(() =>
      expect(onSelect).toHaveBeenCalledWith({ type: 'destination', destination: campinas }),
    );
    expect(mockApi.get).toHaveBeenCalledWith('/v1/destinations/resolve', {
      query: { near: fix.near, near_ts: fix.capturedAt, near_accuracy_m: 35 },
    });
  });

  it('explains a denied permission and an uncovered place', async () => {
    mockPosition.mockResolvedValueOnce({ status: 'denied' });
    await renderUi(<Sheet onSelect={jest.fn()} />);
    await fireEvent.press(screen.getByTestId('where-here'));
    expect(await screen.findByTestId('where-here-message')).toHaveTextContent(
      /Allow location access/,
    );
    mockPosition.mockResolvedValueOnce({ status: 'granted', near: fix.near, fix });
    mockApi.get.mockRejectedValueOnce(
      new ApiProblem({ type: 'x', title: 'x', status: 422, code: 'location_unresolvable' }, 'r'),
    );
    await fireEvent.press(screen.getByTestId('where-here'));
    expect(await screen.findByText(/don't cover where you are yet/)).toBeTruthy();
  });

  it('says when nothing matches and lets you retry a failed search', async () => {
    await renderUi(<Sheet onSelect={jest.fn()} />);
    await fireEvent.changeText(screen.getByTestId('where-input'), 'zzz');
    expect(await screen.findByTestId('where-empty')).toHaveTextContent('Nothing found for “zzz”.');
    await fireEvent.changeText(screen.getByTestId('where-input'), 'boom');
    expect(await screen.findByText('Search failed. Check your connection.')).toBeTruthy();
    expect(screen.getByTestId('where-retry')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('where-clear'));
    expect(await screen.findByTestId('where-here')).toBeTruthy();
  });

  it('offers no current location to guests', async () => {
    useSessionStore.getState().setSignedOut();
    await renderUi(<Sheet onSelect={jest.fn()} />);
    expect(await screen.findByTestId('where-popular-rio-br')).toBeTruthy();
    expect(screen.queryByTestId('where-here')).toBeNull();
  });
});

describe('destination field', () => {
  function Field({ onPlace }: { onPlace?: (id: string) => void }) {
    const [value, setValue] = useState<DestinationSummary | null>(null);
    return (
      <DestinationPicker
        value={value}
        onChange={setValue}
        onPlace={onPlace ? (place) => onPlace(place.id) : undefined}
        testID="field"
        variant="destination"
      />
    );
  }

  it('sets the town of a chosen place when the screen takes destinations only', async () => {
    await renderUi(<Field />);
    expect(screen.getByTestId('field')).toHaveTextContent('Where to?');
    await fireEvent.press(screen.getByTestId('field'));
    await fireEvent.changeText(await screen.findByTestId('field-input'), 'cristo');
    await fireEvent.press(await screen.findByTestId('field-place-p-cristo'));
    expect(screen.getByTestId('field-chosen')).toHaveTextContent(
      /Destination: Rio.*Rio de Janeiro, Brazil/,
    );
    await fireEvent.press(screen.getByTestId('field-clear'));
    expect(screen.getByTestId('field')).toHaveTextContent('Where to?');
  });

  it('hands a chosen place to screens that open places', async () => {
    const onPlace = jest.fn();
    await renderUi(<Field onPlace={onPlace} />);
    await fireEvent.press(screen.getByTestId('field'));
    await fireEvent.changeText(await screen.findByTestId('field-input'), 'cristo');
    await fireEvent.press(await screen.findByTestId('field-place-p-cristo'));
    expect(onPlace).toHaveBeenCalledWith('p-cristo');
    expect(screen.queryByTestId('field-chosen')).toBeNull();
  });
});
