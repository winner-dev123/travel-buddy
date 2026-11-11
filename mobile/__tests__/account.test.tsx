// req: AUTH-010, PROF-004, PROF-008, SAFE-001, SAFE-002, SAFE-013, NOTIF-001
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert } from 'react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { i18n } from '@/i18n';

import Notifications from '../app/notifications';
import Companions from '../app/(tabs)/companions';
import Report from '../app/report';
import Blocked from '../app/settings/blocked';
import DeleteAccount from '../app/settings/delete-account';
import Privacy from '../app/settings/privacy';
import EditProfile from '../app/settings/profile';
import People from '../app/people';
import Follows from '../app/user/follows';
import UserProfile from '../app/user/[id]';
import Profile from '../app/(tabs)/profile';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn() };
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
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

function makeMe(
  overrides: { account?: Partial<Me['account']>; profile?: Partial<Me['profile']> } = {},
): Me {
  return {
    account: {
      id: 'u9',
      email: 'me@example.com',
      email_verified: true,
      status: 'active',
      primary_locale: 'en',
      deletion_scheduled_for: null,
      restrictions: [],
      ...overrides.account,
    },
    profile: {
      id: 'u9',
      handle: 'me',
      display_name: 'Me',
      bio: null,
      account_visibility: 'public',
      ...overrides.profile,
    },
    preferences: { ui_locale: 'en', time_zone: 'UTC' },
    privacy: { discovery_enabled: false, search_engine_indexing: false },
    roles: [],
    onboarding_completed: true,
  };
}

const bo = { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null };

beforeEach(async () => {
  jest.clearAllMocks();
  mockParams = {};
  await i18n.changeLanguage('en');
});

describe('profile tab', () => {
  it('explains a pending deletion and lets the user keep the account', async () => {
    useSessionStore.getState().setSignedIn(
      makeMe({
        account: { status: 'pending_deletion', deletion_scheduled_for: '2026-12-09T10:00:00Z' },
      }),
    );
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/users/me' ? makeMe() : { count: 2 },
    );
    mockApi.delete.mockResolvedValue(undefined);
    await renderScreen(<Profile />);
    expect(screen.getByTestId('profile-deletion-pending')).toBeTruthy();
    expect(screen.queryByTestId('profile-menu-delete')).toBeNull();
    await fireEvent.press(screen.getByTestId('profile-cancel-deletion'));
    await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/users/me/deletion'));
    await waitFor(() => expect(screen.queryByTestId('profile-deletion-pending')).toBeNull());
    expect(await screen.findByLabelText('Notifications, 2')).toBeTruthy();
  });

  it('shows active restrictions and opens settings', async () => {
    useSessionStore.getState().setSignedIn(
      makeMe({
        account: {
          restrictions: [
            { kind: 'posting_limited', reason_code: 'spam', until: null, appealable: true },
          ],
        },
      }),
    );
    mockApi.get.mockResolvedValue({ count: 0 });
    await renderScreen(<Profile />);
    expect(screen.getByTestId('profile-restriction-posting_limited')).toHaveTextContent(
      'Posting is limited on your account.',
    );
    await fireEvent.press(screen.getByTestId('profile-menu-privacy'));
    expect(mockRouter.push).toHaveBeenCalledWith('/settings/privacy');
  });

  it('groups the menu and opens the appearance setting', async () => {
    useSessionStore.getState().setSignedIn(makeMe({ profile: { bio: 'Slow travel' } }));
    mockApi.get.mockResolvedValue({ count: 0 });
    await renderScreen(<Profile />);
    expect(screen.getByTestId('profile-display-name')).toHaveTextContent('Me');
    expect(screen.getByTestId('profile-handle')).toHaveTextContent('@me');
    expect(screen.getByText('Slow travel')).toBeTruthy();
    for (const title of ['Account', 'Your travels', 'Preferences', 'Safety and support']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    await fireEvent.press(screen.getByTestId('profile-menu-appearance'));
    expect(mockRouter.push).toHaveBeenCalledWith('/settings/appearance');
  });
});

describe('settings', () => {
  it('edits the display name and bio', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockApi.patch.mockResolvedValue(
      makeMe({ profile: { display_name: 'Maria', bio: 'Slow travel' } }),
    );
    await renderScreen(<EditProfile />);
    expect(screen.getByTestId('profile-save')).toBeDisabled();
    await fireEvent.changeText(screen.getByTestId('profile-display-name-input'), 'Maria');
    await fireEvent.changeText(screen.getByTestId('profile-bio-input'), ' Slow travel ');
    await fireEvent.press(screen.getByTestId('profile-save'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me', {
        body: { display_name: 'Maria', bio: 'Slow travel' },
      }),
    );
    expect(useSessionStore.getState().me?.profile.display_name).toBe('Maria');
    expect(mockRouter.back).toHaveBeenCalled();
  });

  it('switches to a private account and opts into search indexing', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockApi.patch.mockImplementation(async (path: string) =>
      path === '/v1/users/me' ? makeMe({ profile: { account_visibility: 'private' } }) : {},
    );
    mockApi.get.mockResolvedValue({
      ...makeMe({ profile: { account_visibility: 'private' } }),
      privacy: { discovery_enabled: false, search_engine_indexing: true },
    });
    await renderScreen(<Privacy />);
    await fireEvent(screen.getByTestId('privacy-private-account'), 'valueChange', true);
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me', {
        body: { account_visibility: 'private' },
      }),
    );
    await fireEvent(screen.getByTestId('privacy-search-indexing'), 'valueChange', true);
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me/privacy', {
        body: { search_engine_indexing: true },
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('privacy-search-indexing')).toHaveProp('value', true),
    );
    expect(
      screen.getByText(
        'Private accounts are never shown in search engines, whatever this setting says.',
      ),
    ).toBeTruthy();
  });

  it('lists blocked accounts and unblocks', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockApi.get.mockResolvedValue({ data: [bo], page: { next_cursor: null, has_more: false } });
    mockApi.delete.mockResolvedValue(undefined);
    await renderScreen(<Blocked />);
    expect(await screen.findByTestId('blocked-u2')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('unblock-u2'));
    await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/users/u2/block'));
    expect(await screen.findByTestId('blocked-empty')).toBeTruthy();
  });

  it('requests deletion only after explicit confirmation', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockApi.post.mockResolvedValue({
      id: 'r1',
      status: 'received',
      scheduled_for: '2026-12-09T10:00:00Z',
    });
    mockApi.get.mockResolvedValue(makeMe({ account: { status: 'pending_deletion' } }));
    await renderScreen(<DeleteAccount />);
    expect(screen.getByTestId('delete-submit')).toBeDisabled();
    await fireEvent.changeText(screen.getByTestId('delete-reason'), 'Taking a break');
    await fireEvent(screen.getByTestId('delete-understood'), 'valueChange', true);
    await fireEvent.press(screen.getByTestId('delete-submit'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/deletion', {
        idempotencyKey: 'key-1',
        body: { confirm: true, reason: 'Taking a break' },
      }),
    );
    await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
    expect(useSessionStore.getState().me?.account.status).toBe('pending_deletion');
  });
});

describe('safety', () => {
  it('reports a post with a reason and blocks the author in the same step', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockParams = { type: 'post', target: 'p1', name: 'Bo' };
    mockApi.post.mockResolvedValue({ id: 'rep1', status: 'open' });
    await renderScreen(<Report />);
    expect(screen.getByText("What's wrong with this story?")).toBeTruthy();
    expect(screen.getByTestId('report-submit')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('report-reason-harassment'));
    await fireEvent.changeText(screen.getByTestId('report-details'), 'Keeps insulting people');
    await fireEvent(screen.getByTestId('report-also-block'), 'valueChange', true);
    await fireEvent.press(screen.getByTestId('report-submit'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/reports', {
        body: {
          target_type: 'post',
          target_id: 'p1',
          reason: 'harassment',
          also_block: true,
          details: 'Keeps insulting people',
        },
      }),
    );
    expect(await screen.findByTestId('report-done')).toBeTruthy();
  });

  it('shows urgent guidance for child-safety and self-harm reports', async () => {
    mockParams = { type: 'user', target: 'u2' };
    await renderScreen(<Report />);
    await fireEvent.press(screen.getByTestId('report-reason-minor_safety'));
    expect(
      screen.getByText(
        'If someone is in immediate danger, contact local emergency services first.',
      ),
    ).toBeTruthy();
  });

  it('follows, reports and blocks from another profile', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockParams = { id: 'u2' };
    let followStatus = 'none';
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/users/u2'
        ? {
            ...bo,
            bio: 'Backpacker',
            account_visibility: 'private',
            is_restricted: true,
            counts: null,
            follow_status: followStatus,
          }
        : { data: [], page: { next_cursor: null, has_more: false } },
    );
    mockApi.put.mockImplementation(async (path: string) =>
      path.endsWith('/follow')
        ? ((followStatus = 'requested'), { status: 'requested' })
        : undefined,
    );
    await renderScreen(<UserProfile />);
    expect(
      await screen.findByText('This account is private. Follow to see their stories.'),
    ).toBeTruthy();
    expect(screen.queryByTestId('user-badges')).toBeNull(); // none earned
    await fireEvent.press(screen.getByTestId('user-follow'));
    await waitFor(() => expect(mockApi.put).toHaveBeenCalledWith('/v1/users/u2/follow'));
    expect(await screen.findByText('Requested')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('user-report'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/report',
      params: { type: 'user', target: 'u2', name: 'Bo' },
    });
    const alert = jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, buttons) => {
      buttons?.find((button) => button.style === 'destructive')?.onPress?.();
    });
    await fireEvent.press(screen.getByTestId('user-block'));
    expect(alert).toHaveBeenCalledWith('Block Bo?', expect.any(String), expect.any(Array));
    alert.mockRestore();
    await waitFor(() => expect(mockApi.put).toHaveBeenCalledWith('/v1/users/u2/block'));
    await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
  });
});

describe('notifications', () => {
  it('lists notifications, marks them read and opens the related story', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockApi.get.mockResolvedValue({
      data: [
        {
          id: 'n1',
          type: 'post_reaction',
          actor: bo,
          entity_type: 'post',
          entity_id: 'p1',
          title: 'New reaction',
          body: 'Bo reacted to your post.',
          read_at: null,
          created_at: '2026-11-09T10:00:00Z',
        },
      ],
      page: { next_cursor: null, has_more: false },
    });
    mockApi.post.mockResolvedValue(undefined);
    await renderScreen(<Notifications />);
    expect(await screen.findByText('Bo reacted to your post.')).toBeTruthy();
    // Unread shows as a dot and is said aloud, not left to colour alone.
    expect(screen.getByTestId('notification-unread-n1')).toBeTruthy();
    expect(screen.getByLabelText('Unread. New reaction. Bo reacted to your post.')).toBeTruthy();
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/notifications/read', { body: { all: true } }),
    );
    await fireEvent.press(screen.getByTestId('notification-n1'));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/post/[id]', params: { id: 'p1' } });
  });
});

describe('connections', () => {
  const request = (
    id: string,
    requester = bo,
    recipient = { ...bo, id: 'u9', handle: 'me', display_name: 'Me' },
  ) => ({
    id,
    requester,
    recipient,
    status: 'pending',
    note: 'Met in Lisbon',
    created_at: '2026-11-09T10:00:00Z',
  });

  it('accepts, declines and cancels requests from the Companions tab', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    const cy = { id: 'u3', handle: 'cy', display_name: 'Cy', avatar: null };
    mockApi.get.mockImplementation(
      async (path: string, options?: { query?: { direction?: string } }) => {
        if (path === '/v1/users/me/approximate-location') {
          throw new ApiProblem(
            { type: 'x', title: 'Unknown', status: 422, code: 'location_unresolvable' },
            'r',
          );
        }
        if (path === '/v1/connections/requests') {
          return {
            data:
              options?.query?.direction === 'incoming'
                ? [request('r1'), request('r2', cy)]
                : [request('r3', makeMe().profile as never, cy)],
            page: { next_cursor: null, has_more: false },
          };
        }
        return {
          data: [
            {
              user: { id: 'u4', handle: 'di', display_name: 'Di', avatar: null },
              connected_at: '2026-11-01T10:00:00Z',
            },
          ],
          page: { next_cursor: null, has_more: false },
        };
      },
    );
    mockApi.post.mockResolvedValue({});
    await renderScreen(<Companions />);
    expect(await screen.findByTestId('incoming-r1')).toBeTruthy();
    expect(screen.getAllByText('“Met in Lisbon”').length).toBeGreaterThan(0);
    expect(screen.getByTestId('connection-u4')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('accept-r1'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/connections/requests/r1/accept'),
    );
    await fireEvent.press(screen.getByTestId('decline-r2'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/connections/requests/r2/decline'),
    );
    await fireEvent.press(screen.getByTestId('cancel-r3'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/connections/requests/r3/cancel'),
    );
    expect(screen.getByTestId('discovery-safety-notice')).toBeTruthy();
  });

  it('sends a connection request from a profile', async () => {
    useSessionStore.getState().setSignedIn(makeMe());
    mockParams = { id: 'u2' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/users/u2'
        ? {
            ...bo,
            bio: null,
            account_visibility: 'public',
            is_restricted: false,
            counts: { posts: 0, followers: 0, following: 0 },
            follow_status: 'none',
            relationship: 'none',
            can_request_connection: true,
          }
        : { data: [], page: { next_cursor: null, has_more: false } },
    );
    mockApi.post.mockResolvedValue(request('r9', makeMe().profile as never, bo));
    await renderScreen(<UserProfile />);
    await fireEvent.press(await screen.findByTestId('user-connect'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/connections/requests', {
        idempotencyKey: 'key-1',
        body: { recipient_id: 'u2', context: 'profile' },
      }),
    );
    expect(await screen.findByTestId('user-request-sent')).toBeTruthy();
  });
});

it('shows the badges a traveller earned on their profile', async () => {
  useSessionStore.getState().setSignedIn(makeMe());
  mockParams = { id: 'u2' };
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/users/u2'
      ? {
          ...bo,
          bio: null,
          account_visibility: 'public',
          is_restricted: false,
          counts: { posts: 1, followers: 0, following: 0 },
          follow_status: 'none',
          badges: [{ id: 'b1', key: 'lisbon-quiz', name: 'Lisbon quiz winner', icon: null }],
        }
      : { data: [], page: { next_cursor: null, has_more: false } },
  );
  await renderScreen(<UserProfile />);
  expect(await screen.findByTestId('user-badge-lisbon-quiz')).toHaveTextContent(
    '🏅 Lisbon quiz winner',
  );
});

it('opens follower lists from a profile and lists people', async () => {
  useSessionStore.getState().setSignedIn(makeMe());
  mockParams = { id: 'u2' };
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/users/u2'
      ? {
          ...bo,
          bio: null,
          account_visibility: 'public',
          is_restricted: false,
          counts: { posts: 1, followers: 2, following: 0 },
          follow_status: 'none',
        }
      : { data: [], page: { next_cursor: null, has_more: false } },
  );
  await renderScreen(<UserProfile />);
  expect(await screen.findByLabelText('1 Stories')).toBeTruthy();
  expect(screen.getByLabelText('2 Followers')).toBeTruthy();
  expect(screen.getByLabelText('0 Following')).toBeTruthy();
  await fireEvent.press(await screen.findByTestId('user-followers'));
  expect(mockRouter.push).toHaveBeenCalledWith({
    pathname: '/user/follows',
    params: { id: 'u2', kind: 'followers' },
  });
});

it('lists followers and opens a profile', async () => {
  mockParams = { id: 'u2', kind: 'followers' };
  mockApi.get.mockResolvedValue({
    data: [{ id: 'u3', handle: 'cy', display_name: 'Cy', avatar: null }],
    page: { next_cursor: null, has_more: false },
  });
  await renderScreen(<Follows />);
  await fireEvent.press(await screen.findByTestId('follows-u3'));
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/user/[id]', params: { id: 'u3' } });
  expect(mockApi.get).toHaveBeenCalledWith('/v1/users/u2/followers', {
    query: { cursor: undefined, limit: 30 },
  });
});

it('finds people by name once two characters are typed', async () => {
  mockApi.get.mockResolvedValue({
    data: [{ id: 'u5', handle: 'marta', display_name: 'Marta', avatar: null }],
    page: { next_cursor: null, has_more: false },
  });
  await renderScreen(<People />);
  await fireEvent.changeText(screen.getByTestId('people-query'), 'm');
  expect(mockApi.get).not.toHaveBeenCalled(); // one character is too few
  await fireEvent.changeText(screen.getByTestId('people-query'), 'mar');
  await fireEvent.press(await screen.findByTestId('people-u5'));
  expect(mockApi.get).toHaveBeenCalledWith('/v1/users/search', { query: { q: 'mar', limit: 20 } });
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/user/[id]', params: { id: 'u5' } });
});
