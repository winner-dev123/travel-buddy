// req: POST-005, FEED-020
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Alert, type AlertButton, Share } from 'react-native';
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

describe('feed actions', () => {
  afterEach(() => jest.restoreAllMocks());

  it('hides a story with feedback for the feed', async () => {
    mockApi.post.mockReset();
    mockApi.post.mockResolvedValue(undefined);
    let buttons: AlertButton[] = [];
    jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, given) => {
      buttons = given ?? [];
    });
    await renderUi(<PostCard post={post('p1')} onOpen={jest.fn()} />);
    await fireEvent.press(screen.getByTestId('post-more-p1'));
    expect(buttons.map((b) => b.text)).toEqual([
      'Hide this story',
      'Not interested',
      'See less from Ana',
      'Cancel',
    ]);
    buttons[2]?.onPress?.();
    expect(await screen.findByTestId('post-dismissed-p1')).toHaveTextContent(
      "Hidden. You'll see fewer stories like this.",
    );
    expect(mockApi.post).toHaveBeenCalledWith('/v1/feed/feedback', {
      body: { post_id: 'p1', kind: 'see_less_author' },
    });
  });

  it('shares public stories through the share sheet', async () => {
    mockApi.post.mockReset();
    mockApi.post.mockResolvedValue({ url: 'https://travelbuddy.app/s/abc' });
    const share = jest
      .spyOn(Share, 'share')
      .mockResolvedValue({ action: 'sharedAction', activityType: undefined });
    await renderUi(<PostCard post={post('p1')} />);
    await fireEvent.press(screen.getByTestId('post-share-p1'));
    await waitFor(() =>
      expect(share).toHaveBeenCalledWith({
        message: 'A travel story on Travel Buddy: https://travelbuddy.app/s/abc',
      }),
    );
    expect(mockApi.post).toHaveBeenCalledWith('/v1/posts/p1/shares', {
      body: { channel: 'system_share_sheet' },
    });
  });

  it('offers no share for non-public stories and no feedback on my own or on the story page', async () => {
    const mine = { ...post('p2'), visibility: 'followers' } as Post;
    mine.viewer = { ...mine.viewer!, is_author: true };
    await renderUi(<PostCard post={mine} onOpen={jest.fn()} />);
    expect(screen.queryByTestId('post-share-p2')).toBeNull();
    expect(screen.queryByTestId('post-more-p2')).toBeNull();
  });

  it('offers no feedback menu on the story page itself', async () => {
    await renderUi(<PostCard post={post('p3')} />);
    expect(screen.queryByTestId('post-more-p3')).toBeNull();
  });
});
