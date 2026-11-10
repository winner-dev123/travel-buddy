// req: POST-003, POST-005, SAFE-002
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert, type AlertButton } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Post } from '@/features/feed/types';
import { i18n } from '@/i18n';

import PostDetail from '../app/post/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({ id: 'p1' }),
  Stack: { Screen: () => null },
}));

function post(isAuthor: boolean, overrides: Partial<Post> = {}): Post {
  return {
    id: 'p1',
    author: { id: 'u9', handle: 'me', display_name: 'Me', avatar: null },
    kind: 'tip',
    body: 'Take the 28 tram early',
    language: 'en',
    visibility: 'public',
    primary_destination: null,
    tags: [],
    media: [],
    published_at: '2026-11-09T10:00:00Z',
    edited_at: null,
    counts: { reactions: 0, comments: 0, bookmarks: 0, shares: 0 },
    viewer: {
      reaction: null,
      bookmarked: false,
      is_author: isAuthor,
      can_comment: true,
      can_delete: isAuthor,
    },
    ...overrides,
  } as Post;
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
} as unknown as Me;

function serve(current: Post) {
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/posts/p1' ? current : { data: [], page: { next_cursor: null, has_more: false } },
  );
}

async function renderPost() {
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
        <PostDetail />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  for (const fn of [mockApi.get, mockApi.patch, mockApi.delete, mockRouter.back, mockRouter.push])
    fn.mockReset();
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

afterEach(() => jest.restoreAllMocks());

it('lets the author edit only what changed', async () => {
  serve(post(true));
  mockApi.patch.mockResolvedValue(
    post(true, { body: 'Take the 28 tram before 9am', visibility: 'followers' }),
  );
  await renderPost();
  await fireEvent.press(await screen.findByTestId('post-edit'));
  expect(screen.getByTestId('post-edit-save')).toBeDisabled(); // nothing changed yet
  await fireEvent.changeText(screen.getByTestId('post-edit-body'), 'Take the 28 tram before 9am');
  await fireEvent.press(screen.getByTestId('post-edit-visibility-followers'));
  await fireEvent.press(screen.getByTestId('post-edit-save'));
  await waitFor(() =>
    expect(mockApi.patch).toHaveBeenCalledWith('/v1/posts/p1', {
      body: { body: 'Take the 28 tram before 9am', visibility: 'followers' },
    }),
  );
  expect(await screen.findByText('Take the 28 tram before 9am')).toBeTruthy();
  expect(screen.queryByTestId('post-editor')).toBeNull();
});

it('does not allow emptying a text-only story', async () => {
  serve(post(true));
  await renderPost();
  await fireEvent.press(await screen.findByTestId('post-edit'));
  await fireEvent.changeText(screen.getByTestId('post-edit-body'), '   ');
  expect(screen.getByTestId('post-edit-save')).toBeDisabled();
});

it('deletes after confirming and leaves the story', async () => {
  serve(post(true));
  mockApi.delete.mockResolvedValue(undefined);
  const alert = jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, buttons) => {
    buttons?.find((button) => button.style === 'destructive')?.onPress?.();
  });
  await renderPost();
  await fireEvent.press(await screen.findByTestId('post-delete'));
  expect(alert).toHaveBeenCalledWith('Delete this story?', expect.any(String), expect.any(Array));
  await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/posts/p1'));
  await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
});

it('shows no author tools on other people’s stories', async () => {
  serve(post(false, { author: { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null } }));
  await renderPost();
  expect(await screen.findByTestId('post-report')).toBeTruthy();
  expect(screen.queryByTestId('post-edit')).toBeNull();
  expect(screen.queryByTestId('post-delete')).toBeNull();
});

const comment = (id: string, authorId: string, canDelete: boolean) => ({
  id,
  post_id: 'p1',
  author: {
    id: authorId,
    handle: authorId,
    display_name: authorId === 'u9' ? 'Me' : 'Bo',
    avatar: null,
  },
  body: `Comment ${id}`,
  deleted: false,
  created_at: '2026-11-09T11:00:00Z',
  viewer: { can_edit: authorId === 'u9', can_delete: canDelete },
});

it('deletes comments where allowed and reports other people’s', async () => {
  // On my own story I may delete any comment; I report the ones I didn't write.
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/posts/p1'
      ? post(true)
      : {
          data: [comment('c1', 'u9', true), comment('c2', 'bo', true)],
          page: { next_cursor: null, has_more: false },
        },
  );
  mockApi.delete.mockResolvedValue(undefined);
  let buttons: AlertButton[] = [];
  jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, given) => {
    buttons = given ?? [];
  });
  await renderPost();

  await fireEvent(await screen.findByTestId('comment-c1'), 'longPress');
  expect(buttons.map((b) => b.text)).toEqual(['Delete comment', 'Cancel']);
  buttons[0]?.onPress?.();
  await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/comments/c1'));

  await fireEvent(screen.getByTestId('comment-c2'), 'longPress');
  expect(buttons.map((b) => b.text)).toEqual(['Delete comment', 'Report comment', 'Cancel']);
  buttons[1]?.onPress?.();
  expect(mockRouter.push).toHaveBeenCalledWith({
    pathname: '/report',
    params: { type: 'comment', target: 'c2', name: 'Bo' },
  });
});
