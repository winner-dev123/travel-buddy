// req: GRP-005, GRP-007, GRP-009, GRP-013
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Alert } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Group, GroupMember, GroupRole, OwnershipTransfer } from '@/features/groups/api';
import { i18n } from '@/i18n';

import GroupScreen from '../app/groups/[id]';
import ManageGroup from '../app/groups/manage';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({ id: 'g1' }),
  Stack: { Screen: () => null },
}));

const user = (id: string, name: string) => ({
  id,
  handle: name.toLowerCase(),
  display_name: name,
  avatar: null,
});
const ana = user('ana', 'Ana');
const bo = user('bo', 'Bo');
const cy = user('cy', 'Cy');
const dee = user('dee', 'Dee');

function member(u: ReturnType<typeof user>, role: GroupMember['role']): GroupMember {
  return {
    group_id: 'g1',
    user: u,
    role,
    status: 'active',
    joined_at: '2026-10-01T10:00:00Z',
    restricted_until: null,
  };
}

const MEMBERS = [
  member(ana, 'owner'),
  member(bo, 'admin'),
  member(cy, 'moderator'),
  member(dee, 'member'),
];

function group(role: GroupRole, permissions: string[], overrides: Partial<Group> = {}): Group {
  return {
    id: 'g1',
    name: 'Alfama supper club',
    description: null,
    cover: null,
    primary_destination: {
      id: 'd1',
      kind: 'city',
      slug: 'lisbon-pt',
      path: 'portugal/lisbon',
      name: 'Lisbon',
      country_code: 'PT',
    } as Group['primary_destination'],
    start_date: null,
    end_date: null,
    member_capacity: 8,
    member_count: 4,
    owner: ana,
    status: 'active',
    conversation_id: 'c1',
    premium_features_active: true,
    my_membership: { role, status: 'active', permissions, restricted_until: null },
    version: 1,
    ...overrides,
  };
}

function me(id: string): Me {
  return {
    account: {
      id,
      email: 'me@example.com',
      email_verified: true,
      status: 'active',
      primary_locale: 'en',
    },
    profile: { id, handle: id, display_name: id, bio: null, account_visibility: 'public' },
    preferences: { ui_locale: 'en', time_zone: 'UTC' },
    privacy: { discovery_enabled: false, search_engine_indexing: false },
    roles: [],
    onboarding_completed: true,
  };
}

const OWNER_PERMISSIONS = [
  'group.edit',
  'group.transfer',
  'members.invite',
  'members.remove',
  'members.restrict',
  'roles.assign',
];

function serve(current: Group) {
  mockApi.get.mockImplementation(async (path: string) => {
    if (path === '/v1/groups/g1') return current;
    if (path === '/v1/groups/g1/members')
      return { data: MEMBERS, page: { next_cursor: null, has_more: false } };
    if (path === '/v1/groups/g1/settings')
      return {
        members_can_invite: false,
        chat_mode: 'everyone',
        new_member_history: 'full',
        challenge_defaults: {},
        version: 4,
      };
    throw new Error(`unexpected ${path}`);
  });
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

const confirmAlerts = () =>
  jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, buttons) => {
    buttons?.find((button) => button.style !== 'cancel')?.onPress?.();
  });

beforeEach(async () => {
  for (const fn of [mockApi.get, mockApi.post, mockApi.patch, mockApi.delete, mockRouter.push])
    fn.mockReset();
  await i18n.changeLanguage('en');
});

describe('manage group (owner)', () => {
  it('changes settings with the version it read', async () => {
    useSessionStore.getState().setSignedIn(me('ana'));
    serve(group('owner', OWNER_PERMISSIONS));
    mockApi.patch.mockResolvedValue({
      members_can_invite: true,
      chat_mode: 'everyone',
      new_member_history: 'full',
      challenge_defaults: {},
      version: 5,
    });
    await renderUi(<ManageGroup />);
    await fireEvent(await screen.findByTestId('setting-members-invite'), 'valueChange', true);
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/groups/g1/settings', {
        body: { members_can_invite: true },
        ifMatchVersion: 4,
      }),
    );
  });

  it('assigns roles below its own, removes and offers ownership after confirming', async () => {
    useSessionStore.getState().setSignedIn(me('ana'));
    serve(group('owner', OWNER_PERMISSIONS));
    mockApi.patch.mockResolvedValue(member(dee, 'moderator'));
    mockApi.delete.mockResolvedValue(undefined);
    mockApi.post.mockResolvedValue({
      id: 't1',
      group_id: 'g1',
      from_user: ana,
      to_user: bo,
      status: 'pending',
      created_at: '',
      expires_at: '',
      responded_at: null,
    });
    const alert = confirmAlerts();
    await renderUi(<ManageGroup />);

    await fireEvent.press(await screen.findByTestId('role-dee-moderator'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/groups/g1/members/dee', {
        body: { role: 'moderator' },
      }),
    );
    expect(screen.queryByTestId('role-ana-admin')).toBeNull(); // nobody manages the owner

    await fireEvent.press(screen.getByTestId('remove-cy'));
    await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/groups/g1/members/cy'));

    await fireEvent.press(screen.getByTestId('transfer-bo'));
    expect(alert).toHaveBeenLastCalledWith(
      'Make Bo the owner?',
      expect.any(String),
      expect.any(Array),
    );
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/groups/g1/ownership-transfers', {
        body: { to_user_id: 'bo' },
      }),
    );
    expect(await screen.findByTestId('manage-transfer-sent')).toHaveTextContent(
      'Bo can accept ownership from the group page.',
    );
    alert.mockRestore();
  });
});

describe('manage group (moderator)', () => {
  it('only removes members ranked below, with no settings or roles', async () => {
    useSessionStore.getState().setSignedIn(me('cy'));
    serve(group('moderator', ['members.remove', 'members.restrict']));
    await renderUi(<ManageGroup />);
    expect(await screen.findByTestId('remove-dee')).toBeTruthy();
    expect(screen.queryByTestId('remove-bo')).toBeNull(); // an admin outranks a moderator
    expect(screen.queryByTestId('manage-settings')).toBeNull();
    expect(screen.queryByTestId('role-dee-member')).toBeNull();
    expect(screen.queryByTestId('transfer-dee')).toBeNull();
    expect(mockApi.get).not.toHaveBeenCalledWith('/v1/groups/g1/settings');
  });
});

describe('ownership offers on the group page', () => {
  const offer: OwnershipTransfer = {
    id: 't1',
    group_id: 'g1',
    from_user: ana,
    to_user: bo,
    status: 'pending',
    created_at: '2026-11-10T10:00:00Z',
    expires_at: '2026-11-17T10:00:00Z',
    responded_at: null,
  };

  it('lets the recipient accept', async () => {
    useSessionStore.getState().setSignedIn(me('bo'));
    serve(group('admin', ['members.remove'], { pending_transfer: offer }));
    mockApi.post.mockResolvedValue({ ...offer, status: 'accepted' });
    await renderUi(<GroupScreen />);
    expect(await screen.findByTestId('group-transfer-offer')).toHaveTextContent(
      /^Ana wants to make you the owner of this group\./,
    );
    await fireEvent.press(screen.getByTestId('group-transfer-accept'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/groups/g1/ownership-transfers/t1/accept'),
    );
  });

  it('lets the owner cancel an offer and open the manage screen', async () => {
    useSessionStore.getState().setSignedIn(me('ana'));
    serve(group('owner', OWNER_PERMISSIONS, { pending_transfer: offer }));
    mockApi.post.mockResolvedValue({ ...offer, status: 'cancelled' });
    await renderUi(<GroupScreen />);
    expect(await screen.findByTestId('group-transfer-sent')).toHaveTextContent(
      /^Waiting for Bo to accept ownership\./,
    );
    await fireEvent.press(screen.getByTestId('group-transfer-cancel'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/groups/g1/ownership-transfers/t1/cancel'),
    );
    await fireEvent.press(screen.getByTestId('group-manage'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/groups/manage',
      params: { id: 'g1' },
    });
  });

  it('shows nothing to other members', async () => {
    useSessionStore.getState().setSignedIn(me('dee'));
    serve(group('member', [], { pending_transfer: null }));
    await renderUi(<GroupScreen />);
    expect(await screen.findByTestId('group-summary')).toBeTruthy();
    expect(screen.queryByTestId('group-transfer-offer')).toBeNull();
    expect(screen.queryByTestId('group-manage')).toBeNull();
  });
});
