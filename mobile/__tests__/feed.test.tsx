// req: FEED-001, POST-001
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { FeedPage, Post } from '@/features/feed/types';
import { ApiProblem } from '@/api';
import { i18n } from '@/i18n';

import Compose from '../app/compose';
import PostDetail from '../app/post/[id]';
import Home from '../app/(tabs)/index';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn() };

let mockPermission = 'granted';
jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: mockPermission })),
  getLastKnownPositionAsync: jest.fn(async () => ({
    coords: { latitude: 38.72231, longitude: -9.13934, accuracy: 1200 },
    timestamp: Date.now(),
  })),
  getCurrentPositionAsync: jest.fn(),
  Accuracy: { Low: 2 },
}));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({ id: 'p1' }),
  Stack: { Screen: () => null },
}));

async function renderScreen(ui: ReactElement) {
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

const lisbon = {
  id: 'd-lisbon',
  kind: 'city',
  slug: 'lisbon-pt',
  path: 'portugal/lisbon',
  name: 'Lisbon',
  country_code: 'PT',
  country_name: 'Portugal',
};

function post(id: string, overrides: Partial<Post> = {}): Post {
  return {
    id,
    author: { id: 'u1', handle: 'ana', display_name: 'Ana Souza', avatar: null },
    kind: 'tip',
    body: `Story ${id}`,
    language: 'en',
    visibility: 'public',
    primary_destination: lisbon,
    tags: ['food'],
    media: [],
    published_at: '2026-11-09T10:00:00Z',
    edited_at: null,
    counts: { reactions: 2, comments: 1, bookmarks: 0, shares: 0 },
    viewer: {
      reaction: null,
      bookmarked: false,
      is_author: false,
      can_comment: true,
      can_delete: false,
    },
    ...overrides,
  };
}

function page(posts: Post[], source: 'selected' | 'following' = 'selected'): FeedPage {
  return {
    data: posts,
    page: { next_cursor: null, has_more: false, reset: false },
    context: { destination: source === 'selected' ? lisbon : null, source, radius_km: null },
  };
}

const me = {
  account: {
    id: 'u9',
    email: 'me@example.com',
    email_verified: true,
    status: 'active',
    primary_locale: 'en',
  },
  profile: { id: 'u9', handle: 'me', display_name: 'Me', bio: null, account_visibility: 'public' },
  preferences: { ui_locale: 'en', time_zone: 'UTC' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: true,
} as Me;

beforeEach(async () => {
  jest.clearAllMocks();
  await i18n.changeLanguage('en');
});

describe('home feed (signed in)', () => {
  beforeEach(() => {
    useSessionStore.getState().setSignedIn(me);
    mockApi.get.mockImplementation(async (path: string, options?: { query?: { tab?: string } }) => {
      if (path === '/v1/feed') {
        return options?.query?.tab === 'following'
          ? page([post('f1', { body: 'From someone I follow' })], 'following')
          : page([post('p1'), post('p2')]);
      }
      throw new Error(`unexpected GET ${path}`);
    });
    mockApi.post.mockResolvedValue({});
  });

  it('shows ranked stories with the fallback context and switches tabs', async () => {
    await renderScreen(<Home />);
    expect(await screen.findByText('Story p1')).toBeTruthy();
    expect(screen.getByText('Story p2')).toBeTruthy();
    expect(screen.getByTestId('feed-context')).toHaveTextContent('Stories from Lisbon');
    expect(screen.getAllByText('@ana · Lisbon · Tip')).toHaveLength(2);

    await fireEvent.press(screen.getByTestId('feed-tab-following'));
    expect(await screen.findByText('From someone I follow')).toBeTruthy();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/feed', {
      query: { tab: 'following', cursor: undefined, limit: 20 },
    });
  });

  it('likes a story optimistically and opens it', async () => {
    await renderScreen(<Home />);
    await screen.findByText('Story p1');
    await fireEvent.press(screen.getByTestId('post-like-p1'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/posts/p1/reactions', {
        body: { reaction: 'like' },
      }),
    );
    expect(screen.getByTestId('post-likes-p1')).toHaveTextContent('3');
    await fireEvent.press(screen.getByTestId('post-card-p1'));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/post/[id]', params: { id: 'p1' } });
  });

  it('reverts the like when the request fails', async () => {
    mockApi.post.mockRejectedValueOnce(new Error('offline'));
    await renderScreen(<Home />);
    await screen.findByText('Story p1');
    await fireEvent.press(screen.getByTestId('post-like-p1'));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('post-likes-p1')).toHaveTextContent('2'));
  });
});

describe('nearby and filters', () => {
  beforeEach(() => {
    mockPermission = 'granted';
    useSessionStore.getState().setSignedIn(me);
    mockApi.get.mockImplementation(async () => page([post('n1')]));
  });

  // req: LOC-007, LOC-008
  it('sends only a coarse position for the Nearby tab, with its time and accuracy', async () => {
    await renderScreen(<Home />);
    await screen.findByText('Story n1');
    await fireEvent.press(screen.getByTestId('feed-tab-nearby'));
    await waitFor(() =>
      expect(mockApi.get).toHaveBeenCalledWith('/v1/feed', {
        query: {
          tab: 'nearby',
          cursor: undefined,
          limit: 20,
          near: '38.72,-9.14',
          radius_km: 10,
          near_ts: expect.any(String),
          near_accuracy_m: 1200,
        },
      }),
    );
  });

  // req: LOC-007
  it('locates again instead of sending a fix older than the API accepts', async () => {
    const located = jest.requireMock<{ getLastKnownPositionAsync: jest.Mock }>('expo-location');
    located.getLastKnownPositionAsync.mockResolvedValueOnce({
      coords: { latitude: 38.72231, longitude: -9.13934, accuracy: 1200 },
      timestamp: Date.now() - 20 * 60_000,
    });
    await renderScreen(<Home />);
    await screen.findByText('Story n1');
    await fireEvent.press(screen.getByTestId('feed-tab-nearby'));
    await waitFor(() =>
      expect(mockApi.get).toHaveBeenCalledWith(
        '/v1/feed',
        expect.objectContaining({ query: expect.objectContaining({ tab: 'nearby' }) }),
      ),
    );
    const nearbyCall = mockApi.get.mock.calls.find(
      ([path, options]) => path === '/v1/feed' && options.query.tab === 'nearby',
    );
    expect(Date.now() - Date.parse(nearbyCall?.[1].query.near_ts)).toBeLessThan(60_000);
    expect(located.getLastKnownPositionAsync).toHaveBeenCalledTimes(2);
  });

  it('explains a denied permission without calling the feed', async () => {
    mockPermission = 'denied';
    await renderScreen(<Home />);
    await screen.findByText('Story n1');
    await fireEvent.press(screen.getByTestId('feed-tab-nearby'));
    expect(await screen.findByTestId('feed-nearby-denied')).toBeTruthy();
    expect(mockApi.get).not.toHaveBeenCalledWith(
      '/v1/feed',
      expect.objectContaining({ query: expect.objectContaining({ tab: 'nearby' }) }),
    );
  });

  it('tells the user when the area is not covered yet', async () => {
    mockApi.get.mockImplementation(async (_path: string, options: { query: { tab: string } }) => {
      if (options.query.tab === 'nearby') {
        throw new ApiProblem(
          { type: 'x', title: 'No', status: 422, code: 'location_unresolvable' },
          'req-1',
        );
      }
      return page([post('n1')]);
    });
    await renderScreen(<Home />);
    await screen.findByText('Story n1');
    await fireEvent.press(screen.getByTestId('feed-tab-nearby'));
    expect(await screen.findByTestId('feed-nearby-uncovered')).toBeTruthy();
    expect(screen.queryByTestId('feed-error')).toBeNull();
  });

  it('filters by story type', async () => {
    await renderScreen(<Home />);
    await screen.findByText('Story n1');
    await fireEvent.press(screen.getByTestId('feed-filter-tip'));
    await waitFor(() =>
      expect(mockApi.get).toHaveBeenCalledWith('/v1/feed', {
        query: { tab: 'for_you', cursor: undefined, limit: 20, category: ['tip'] },
      }),
    );
  });
});

describe('guest mode', () => {
  it('browses public stories without interactions', async () => {
    useSessionStore.getState().setSignedOut();
    mockApi.get.mockResolvedValue({
      data: [post('g1', { viewer: undefined })],
      page: { next_cursor: null, has_more: false },
    });
    await renderScreen(<Home />);
    expect(await screen.findByText('Story g1')).toBeTruthy();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/public/posts', {
      query: { cursor: undefined, limit: 20 },
    });
    expect(screen.getByTestId('feed-guest-notice')).toBeTruthy();
    expect(screen.queryByTestId('feed-compose')).toBeNull();
    expect(screen.getByTestId('post-like-g1')).toBeDisabled();
  });
});

describe('post detail', () => {
  it('lists comments and sends one with an idempotency key', async () => {
    useSessionStore.getState().setSignedIn(me);
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/posts/p1') return post('p1');
      if (path === '/v1/posts/p1/comments') {
        return {
          data: [
            {
              id: 'c1',
              post_id: 'p1',
              author: { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null },
              body: 'Great tip!',
              deleted: false,
              created_at: '2026-11-09T11:00:00Z',
            },
          ],
          page: { next_cursor: null, has_more: false },
        };
      }
      throw new Error(`unexpected GET ${path}`);
    });
    mockApi.post.mockResolvedValue({ id: 'c2' });
    await renderScreen(<PostDetail />);
    expect(await screen.findByText('Great tip!')).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('comment-input'), '  Thanks!  ');
    await fireEvent.press(screen.getByTestId('comment-send'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/posts/p1/comments', {
        body: { body: 'Thanks!' },
        idempotencyKey: 'key-1',
      }),
    );
  });
});

describe('composer', () => {
  it('requires a place for recommendations and publishes with the destination', async () => {
    useSessionStore.getState().setSignedIn(me);
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/destinations/search') {
        return { data: [lisbon], page: { next_cursor: null, has_more: false } };
      }
      return page([]);
    });
    mockApi.post.mockResolvedValue(post('new'));
    await renderScreen(<Compose />);

    expect(screen.getByTestId('compose-publish')).toBeDisabled();
    await fireEvent.changeText(
      screen.getByTestId('compose-body'),
      'Try the custard tarts in Belém',
    );
    expect(screen.getByTestId('compose-publish')).toBeEnabled();
    await fireEvent.press(screen.getByTestId('compose-kind-restaurant_recommendation'));
    expect(screen.getByTestId('compose-publish')).toBeDisabled();

    await fireEvent.changeText(screen.getByTestId('compose-search'), 'lis');
    await fireEvent.press(await screen.findByTestId('compose-match-lisbon-pt'));
    expect(screen.getByTestId('compose-destination')).toHaveTextContent('Lisbon, Portugal');
    await fireEvent.press(screen.getByTestId('compose-publish'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/posts', {
        idempotencyKey: 'key-1',
        body: {
          kind: 'restaurant_recommendation',
          body: 'Try the custard tarts in Belém',
          visibility: 'public',
          location_precision: 'destination',
          destination_id: 'd-lisbon',
        },
      }),
    );
    await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
  });

  // req: POST-002
  it('tags a public place and files the story under it', async () => {
    useSessionStore.getState().setSignedIn(me);
    const pasteis = {
      id: 'pl-1',
      name: 'Pastéis de Belém',
      category: 'cafe',
      destination_id: 'd-lisbon',
      location: { lat: 38.6975, lng: -9.2033 },
    };
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/destinations/search') {
        return { data: [lisbon], page: { next_cursor: null, has_more: false } };
      }
      if (path === '/v1/places/search') {
        return { data: [pasteis], page: { next_cursor: null, has_more: false } };
      }
      return page([]);
    });
    mockApi.post.mockResolvedValue(post('new'));
    await renderScreen(<Compose />);
    await fireEvent.changeText(screen.getByTestId('compose-body'), 'Still warm at 8 a.m.');
    await fireEvent.changeText(screen.getByTestId('compose-search'), 'lis');
    await fireEvent.press(await screen.findByTestId('compose-match-lisbon-pt'));
    await fireEvent.changeText(screen.getByTestId('compose-spot-search'), 'pastéis');
    await fireEvent.press(await screen.findByTestId('compose-spot-pl-1'));
    expect(screen.getByTestId('compose-spot')).toHaveTextContent('📍 Pastéis de Belém');
    expect(mockApi.get).toHaveBeenCalledWith('/v1/places/search', {
      query: { q: 'pastéis', destination_id: 'd-lisbon', limit: 20 },
    });
    await fireEvent.press(screen.getByTestId('compose-publish'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/posts', {
        idempotencyKey: 'key-1',
        body: {
          kind: 'tip',
          body: 'Still warm at 8 a.m.',
          visibility: 'public',
          location_precision: 'place',
          place_id: 'pl-1',
        },
      }),
    );
  });
});
