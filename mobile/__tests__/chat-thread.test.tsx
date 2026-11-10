// req: GCHAT-002, GCHAT-004
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { messageKeys, type Conversation, type Message } from '@/features/messages/api';
import { i18n } from '@/i18n';

import Chat from '../app/chat/[id]';
import Thread from '../app/chat/thread';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'client-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Stack: { Screen: () => null },
}));

const me: Me = {
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
};
const bo = { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null };
const meSummary = { id: 'u9', handle: 'me', display_name: 'Me', avatar: null };

const groupChat: Conversation = {
  id: 'c1',
  kind: 'group',
  title: 'Lisbon food crawl',
  group_id: null,
  counterpart: null,
  last_message: null,
  last_seq: 3,
  unread_count: 0,
  read_through_seq: 3,
  delivered_through_seq: 3,
  muted_until: null,
  notification_level: 'all',
  can_send: true,
  send_restriction: null,
  created_at: '2026-11-09T09:00:00Z',
  last_message_at: '2026-11-09T10:00:00Z',
};

function message(id: string, seq: number, sender: typeof bo, body: string, extra = {}): Message {
  return {
    id,
    conversation_id: 'c1',
    seq,
    sender,
    kind: 'text',
    body,
    attachments: [],
    reply_to: null,
    thread_root_id: null,
    thread_reply_count: 0,
    reactions: [],
    pinned: false,
    moderation_state: 'visible',
    edited_at: null,
    deleted_at: null,
    created_at: '2026-11-09T10:00:00Z',
    ...extra,
  };
}

const root = message('m1', 1, bo, 'Dinner at 8?', { thread_reply_count: 2 });
const page = (data: Message[]) => ({
  data,
  page: { has_more: false, oldest_seq: data[0]?.seq ?? null, newest_seq: data.at(-1)?.seq ?? null },
});

async function renderWith(ui: ReactElement, seed?: (client: QueryClient) => void) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, refetchInterval: false },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  seed?.(client);
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
  jest.clearAllMocks();
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

it('opens a thread from its reply count in a group chat', async () => {
  mockParams = { id: 'c1' };
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/conversations/c1' ? groupChat : page([root]),
  );
  mockApi.put.mockResolvedValue({});
  await renderWith(<Chat />);
  await fireEvent.press(await screen.findByTestId('thread-link-m1'));
  expect(screen.getByTestId('thread-link-m1')).toHaveTextContent('2 replies');
  expect(mockRouter.push).toHaveBeenCalledWith({
    pathname: '/chat/thread',
    params: { id: 'c1', root: 'm1' },
  });
});

it('shows the thread and replies in it', async () => {
  mockParams = { id: 'c1', root: 'm1' };
  const first = message('m2', 2, meSummary, 'Count me in', { thread_root_id: 'm1' });
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/conversations/c1' ? groupChat : page([first]),
  );
  mockApi.post.mockResolvedValue(
    message('m3', 3, meSummary, 'I will book the table', { thread_root_id: 'm1' }),
  );
  await renderWith(<Thread />, (client) =>
    client.setQueryData(messageKeys.history('c1'), page([root])),
  );
  expect(await screen.findByText('Count me in')).toBeTruthy();
  expect(screen.getByTestId('thread-root')).toHaveTextContent('BoDinner at 8?');
  expect(mockApi.get).toHaveBeenCalledWith('/v1/conversations/c1/threads/m1', {
    query: { limit: 200 },
  });

  await fireEvent.changeText(screen.getByTestId('thread-input'), ' I will book the table ');
  await fireEvent.press(screen.getByTestId('thread-send'));
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
      idempotencyKey: 'client-1',
      body: { client_message_id: 'client-1', body: 'I will book the table', thread_root_id: 'm1' },
    }),
  );
  expect(await screen.findByText('I will book the table')).toBeTruthy();
});

it('says when a thread has no replies yet', async () => {
  mockParams = { id: 'c1', root: 'm1' };
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/conversations/c1' ? { ...groupChat, can_send: false } : page([]),
  );
  await renderWith(<Thread />);
  expect(await screen.findByTestId('thread-empty')).toBeTruthy();
  expect(screen.getByText('Replies to an earlier message')).toBeTruthy();
  expect(screen.queryByTestId('thread-input')).toBeNull();
});
