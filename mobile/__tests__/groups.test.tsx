// req: GRP-001, GRP-005, GRP-008, GCHAT-001, GCHAT-003
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Share } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { tokenFrom, type Group } from '@/features/groups/api';
import { i18n } from '@/i18n';

import Messages from '../app/(tabs)/messages';
import Chat from '../app/chat/[id]';
import GroupScreen from '../app/groups/[id]';
import Groups from '../app/groups/index';
import NewGroup from '../app/groups/new';

/** The "Where to?" field opens the full-screen search; type, then pick a result (ADR-0035). */
async function pickDestination(testID: string, text: string, slug: string) {
  await fireEvent.press(await screen.findByTestId(testID));
  await fireEvent.changeText(await screen.findByTestId(`${testID}-input`), text);
  await fireEvent.press(await screen.findByTestId(`${testID}-${slug}`));
}

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
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

function me(premium: boolean): Me {
  return {
    account: {
      id: 'u9',
      email: 'me@example.com',
      email_verified: true,
      status: 'active',
      primary_locale: 'en',
    },
    profile: {
      id: 'u9',
      handle: 'me',
      display_name: 'Me',
      bio: null,
      account_visibility: 'public',
    },
    preferences: { ui_locale: 'en', time_zone: 'UTC' },
    privacy: { discovery_enabled: false, search_engine_indexing: false },
    roles: [],
    onboarding_completed: true,
    entitlements: {
      plan: premium ? 'premium' : 'free',
      features: { 'groups.create': premium },
    },
  };
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
const ana = { id: 'u1', handle: 'ana', display_name: 'Ana', avatar: null };
const summary = {
  id: 'g1',
  name: 'Alfama supper club',
  cover: null,
  primary_destination: lisbon,
  member_count: 3,
};
const TOKEN = 'A'.repeat(43);

function group(overrides: Partial<Group> = {}): Group {
  return {
    id: 'g1',
    name: 'Alfama supper club',
    description: 'Tascas and fado',
    cover: null,
    primary_destination: lisbon as Group['primary_destination'],
    start_date: null,
    end_date: null,
    member_capacity: 8,
    member_count: 3,
    owner: ana,
    status: 'active',
    conversation_id: 'c-group',
    premium_features_active: true,
    my_membership: {
      role: 'admin',
      status: 'active',
      permissions: ['members.invite', 'members.remove'],
      restricted_until: null,
    },
    version: 1,
    ...overrides,
  };
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockParams = {};
  await i18n.changeLanguage('en');
});

it('reads invitation tokens from pasted links or bare codes', () => {
  expect(tokenFrom(`https://travelbuddy.app/invite#t=${TOKEN}`)).toBe(TOKEN);
  expect(tokenFrom(`  ${TOKEN} `)).toBe(TOKEN);
});

describe('groups list', () => {
  function serve(groups: Group[] = [], invitations: unknown[] = []) {
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/groups'
        ? { data: groups, page: { next_cursor: null, has_more: false } }
        : { data: invitations, page: { next_cursor: null, has_more: false } },
    );
  }

  it('lists groups and answers invitations; free accounts see the premium note', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    serve(
      [group()],
      [
        {
          id: 'i1',
          group: summary,
          kind: 'direct',
          created_by: ana,
          expires_at: '2026-12-01T00:00:00Z',
          status: 'active',
        },
      ],
    );
    mockApi.post.mockResolvedValue({});
    await renderUi(<Groups />);
    expect(await screen.findByText('Lisbon · 3 members')).toBeTruthy();
    expect(screen.getByText('Invited by Ana')).toBeTruthy();
    expect(screen.getByTestId('groups-premium-note')).toBeTruthy();
    expect(screen.queryByTestId('groups-create')).toBeNull();
    await fireEvent.press(screen.getByTestId('groups-see-premium'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/paywall',
      params: { reason: 'groups.create' },
    });
    await fireEvent.press(screen.getByTestId('invitation-accept-i1'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/group-invitations/i1/accept'),
    );
    await fireEvent.press(screen.getByTestId('group-g1'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/groups/[id]',
      params: { id: 'g1' },
    });
  });

  it('previews and redeems a pasted invitation link', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    serve();
    mockApi.post.mockImplementation(async (path: string) =>
      path.endsWith('/preview')
        ? { group: summary, inviter: ana, expires_at: '2026-12-01T00:00:00Z', is_member: false }
        : {
            group_id: 'g1',
            user: ana,
            role: 'member',
            status: 'active',
            joined_at: 'x',
            restricted_until: null,
          },
    );
    await renderUi(<Groups />);
    expect(await screen.findByTestId('groups-create')).toBeTruthy();
    await fireEvent.changeText(
      screen.getByTestId('groups-join-code'),
      `https://travelbuddy.app/invite#t=${TOKEN}`,
    );
    await fireEvent.press(screen.getByTestId('groups-check'));
    expect(await screen.findByTestId('groups-preview')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('groups-join'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/group-invitations/redeem', {
        body: { token: TOKEN },
      }),
    );
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/groups/[id]',
      params: { id: 'g1' },
    });
  });

  it('explains invalid invitations without saying why', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    serve();
    mockApi.post.mockRejectedValue(
      new ApiProblem(
        { type: 'x', title: 'Conflict', status: 409, code: 'invitation_invalid' },
        'r',
      ),
    );
    await renderUi(<Groups />);
    await fireEvent.changeText(await screen.findByTestId('groups-join-code'), TOKEN);
    await fireEvent.press(screen.getByTestId('groups-check'));
    expect(
      await screen.findByText("This invitation isn't valid. Ask for a new link."),
    ).toBeTruthy();
  });
});

describe('group screen', () => {
  it('shows members, opens the chat, shares an invitation link and leaves', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    mockParams = { id: 'g1' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/groups/g1'
        ? group()
        : {
            data: [
              {
                group_id: 'g1',
                user: ana,
                role: 'owner',
                status: 'active',
                joined_at: 'x',
                restricted_until: null,
              },
            ],
            page: { next_cursor: null, has_more: false },
          },
    );
    mockApi.post.mockImplementation(async (path: string) =>
      path.endsWith('/invitations')
        ? { invitation: {}, token: TOKEN, url: `https://travelbuddy.app/invite#t=${TOKEN}` }
        : undefined,
    );
    const share = jest
      .spyOn(Share, 'share')
      .mockResolvedValue({ action: 'sharedAction', activityType: undefined });
    await renderUi(<GroupScreen />);
    expect(await screen.findByTestId('member-u1')).toHaveTextContent(/Ana.*Owner/);
    await fireEvent.press(screen.getByTestId('group-open-chat'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/chat/[id]',
      params: { id: 'c-group' },
    });
    await fireEvent.press(screen.getByTestId('group-invite'));
    await waitFor(() => expect(share).toHaveBeenCalled());
    expect(share.mock.calls[0]?.[0]).toEqual({
      message: `Join my Travel Buddy group: https://travelbuddy.app/invite#t=${TOKEN}`,
    });
    await fireEvent.press(screen.getByTestId('group-leave'));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalledWith('/v1/groups/g1/leave'));
    await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
    share.mockRestore();
  });
});

describe('new group', () => {
  it('creates a group at a chosen destination', async () => {
    useSessionStore.getState().setSignedIn(me(true));
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/destinations/suggest'
        ? {
            data: [{ type: 'destination', destination: lisbon }],
            page: { next_cursor: null, has_more: false },
          }
        : { data: [lisbon], page: { next_cursor: null, has_more: false } },
    );
    mockApi.post.mockResolvedValue(group());
    await renderUi(<NewGroup />);
    await fireEvent.changeText(screen.getByTestId('group-name'), 'Alfama supper club');
    await pickDestination('group-destination', 'lis', 'lisbon-pt');
    await fireEvent.changeText(screen.getByTestId('group-capacity'), '8');
    await fireEvent.press(screen.getByTestId('group-create'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/groups', {
        idempotencyKey: 'key-1',
        body: {
          name: 'Alfama supper club',
          primary_destination_id: 'd-lisbon',
          member_capacity: 8,
        },
      }),
    );
    expect(mockRouter.replace).toHaveBeenCalledWith({
      pathname: '/groups/[id]',
      params: { id: 'g1' },
    });
  });
});

describe('group conversations', () => {
  const convo = {
    id: 'c-group',
    kind: 'group',
    title: 'Alfama supper club',
    counterpart: null,
    last_message: {
      id: 'm1',
      seq: 1,
      sender_id: 'u1',
      kind: 'announcement',
      snippet: 'Meet at 8',
      deleted: false,
      created_at: 'x',
    },
    last_seq: 1,
    unread_count: 1,
    read_through_seq: 1,
    delivered_through_seq: 1,
    muted_until: null,
    notification_level: 'all',
    can_send: true,
    send_restriction: null,
    created_at: 'x',
    last_message_at: '2026-11-09T10:00:00Z',
  };

  it('show the group name in the inbox', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    mockApi.get.mockResolvedValue({ data: [convo], page: { next_cursor: null, has_more: false } });
    await renderUi(<Messages />);
    expect(await screen.findByText('Alfama supper club')).toBeTruthy();
  });

  // Separate tests: unmounting by hand and then auto-cleanup left the chat (and its polling)
  // mounted, which kept Jest from exiting.
  it('show sender names and announcements in the chat', async () => {
    useSessionStore.getState().setSignedIn(me(false));
    mockParams = { id: 'c-group' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/conversations/c-group'
        ? convo
        : {
            data: [
              {
                id: 'm1',
                conversation_id: 'c-group',
                seq: 1,
                sender: ana,
                kind: 'announcement',
                body: 'Meet at 8',
                attachments: [],
                reply_to: null,
                reactions: [],
                pinned: true,
                moderation_state: 'visible',
                edited_at: null,
                deleted_at: null,
                created_at: 'x',
              },
            ],
            page: { has_more: false, oldest_seq: 1, newest_seq: 1 },
          },
    );
    await renderUi(<Chat />);
    expect(await screen.findByTestId('announcement-m1')).toHaveTextContent('Announcement');
    expect(screen.getByText('Ana')).toBeTruthy();
  });
});
