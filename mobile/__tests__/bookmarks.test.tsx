// req: POST-005
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { PostCard } from '@/features/feed/PostCard';
import type { Post } from '@/features/feed/types';
import { i18n } from '@/i18n';

import SavedStories from '../app/bookmarks';

const mockApi = { get: jest.fn(), put: jest.fn(), delete: jest.fn(), post: jest.fn() };
const mockRouter = { push: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ useRouter: () => mockRouter, Stack: { Screen: () => null } }));

function post(id: string, bookmarked = false): Post {
  return {
    id,
    author: { id: 'u1', handle: 'ana', display_name: 'Ana', avatar: null },
    kind: 'tip',
    body: `Story ${id}`,
    language: 'en',
    visibility: 'public',
    primary_destination: null,
    tags: [],
    media: [],
    published_at: '2026-11-09T10:00:00Z',
    edited_at: null,
    counts: { reactions: 0, comments: 0, bookmarks: 0, shares: 0 },
    viewer: { reaction: null, bookmarked, is_author: false, can_comment: true, can_delete: false },
  } as Post;
}

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

beforeEach(async () => {
  for (const fn of [mockApi.get, mockApi.put, mockApi.delete, mockRouter.push]) fn.mockReset();
  await i18n.changeLanguage('en');
});

it('saves and unsaves a story, reverting when the server refuses', async () => {
  mockApi.put.mockResolvedValueOnce(undefined);
  mockApi.delete.mockRejectedValueOnce(new Error('offline'));
  await renderUi(<PostCard post={post('p1')} />);
  const save = screen.getByTestId('post-save-p1');
  expect(save).toHaveProp('accessibilityLabel', 'Save story');

  await fireEvent.press(save);
  await waitFor(() => expect(mockApi.put).toHaveBeenCalledWith('/v1/posts/p1/bookmark'));
  await waitFor(() =>
    expect(screen.getByTestId('post-save-p1')).toHaveProp(
      'accessibilityLabel',
      'Remove from saved',
    ),
  );

  await fireEvent.press(screen.getByTestId('post-save-p1'));
  await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/posts/p1/bookmark'));
  await waitFor(() =>
    expect(screen.getByTestId('post-save-p1')).toHaveProp(
      'accessibilityLabel',
      'Remove from saved',
    ),
  ); // the delete failed: still saved
});

it('hides saving from guests', async () => {
  await renderUi(<PostCard post={post('p1')} interactive={false} />);
  expect(screen.queryByTestId('post-save-p1')).toBeNull();
});

it('lists saved stories and opens one', async () => {
  mockApi.get.mockResolvedValue({
    data: [post('p1', true), post('p2', true)],
    page: { next_cursor: null, has_more: false },
  });
  await renderUi(<SavedStories />);
  expect(await screen.findByTestId('post-card-p1')).toBeTruthy();
  expect(mockApi.get).toHaveBeenCalledWith('/v1/users/me/bookmarks', {
    query: { cursor: undefined, limit: 20 },
  });
  await fireEvent.press(screen.getByTestId('post-card-p2'));
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/post/[id]', params: { id: 'p2' } });
});

it('explains an empty list', async () => {
  mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } });
  await renderUi(<SavedStories />);
  expect(await screen.findByTestId('bookmarks-empty')).toHaveTextContent(
    'Stories you save appear here. Only you can see them.',
  );
});
