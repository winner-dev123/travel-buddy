// req: DM-001, DM-005, DM-007, DM-010, DM-012, SAFE-006
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Alert } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Conversation, Message } from '@/features/messages/api';
import { useOutboxStore } from '@/features/messages/outbox';
import { i18n } from '@/i18n';

import Messages from '../app/(tabs)/messages';
import Chat from '../app/chat/[id]';
import UserProfile from '../app/user/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
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

function testClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, refetchInterval: false },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
}

async function renderUi(ui: ReactElement, client: QueryClient = testClient()) {
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

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 'c1',
    kind: 'direct',
    title: null,
    counterpart: bo,
    last_message: {
      id: 'm2',
      seq: 2,
      sender_id: 'u9',
      kind: 'text',
      snippet: 'See you at 8',
      deleted: false,
      created_at: '2026-11-09T10:00:00Z',
    },
    last_seq: 2,
    unread_count: 0,
    read_through_seq: 1,
    delivered_through_seq: 1,
    peer_read_through_seq: 2,
    peer_delivered_through_seq: 2,
    muted_until: null,
    notification_level: 'all',
    can_send: true,
    send_restriction: null,
    created_at: '2026-11-09T09:00:00Z',
    last_message_at: '2026-11-09T10:00:00Z',
    ...overrides,
  };
}

function message(id: string, seq: number, sender: typeof bo, body: string | null): Message {
  return {
    id,
    conversation_id: 'c1',
    seq,
    sender,
    kind: 'text',
    body,
    attachments: [],
    reply_to: null,
    reactions: [],
    pinned: false,
    moderation_state: 'visible',
    edited_at: null,
    deleted_at: null,
    created_at: '2026-11-09T10:00:00Z',
  };
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockParams = {};
  useSessionStore.getState().setSignedIn(me);
  useOutboxStore.setState({ items: [] });
  await i18n.changeLanguage('en');
});

describe('inbox', () => {
  it('lists conversations with previews and unread counts and opens a chat', async () => {
    mockApi.get.mockResolvedValue({
      data: [
        conversation(),
        conversation({
          id: 'c2',
          counterpart: { ...bo, id: 'u3', display_name: 'Cy' },
          unread_count: 3,
          last_message: { ...conversation().last_message!, sender_id: 'u3', snippet: 'Hi!' },
        }),
        conversation({
          id: 'c3',
          counterpart: { ...bo, id: 'u4', display_name: 'Di' },
          last_message: {
            ...conversation().last_message!,
            sender_id: 'u4',
            kind: 'gift',
            snippet: null,
          },
        }),
      ],
      page: { next_cursor: null, has_more: false },
    });
    await renderUi(<Messages />);
    expect(await screen.findByText('You: See you at 8')).toBeTruthy();
    expect(screen.getByText('Hi!')).toBeTruthy();
    expect(screen.getByText('🎁 Gift')).toBeTruthy(); // DM-016
    expect(screen.getByTestId('conversation-unread-c2')).toHaveTextContent('3');
    expect(screen.getByLabelText('Cy, 3 unread messages')).toBeTruthy();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/conversations', { query: { limit: 50 } });
    await fireEvent.press(screen.getByTestId('conversation-c2'));
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/chat/[id]', params: { id: 'c2' } });
  });

  it('explains how to start when there are no conversations', async () => {
    mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } });
    await renderUi(<Messages />);
    expect(await screen.findByTestId('messages-empty')).toBeTruthy();
  });
});

describe('chat', () => {
  function serve(convo: Conversation, messages: Message[]) {
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/conversations/c1'
        ? convo
        : {
            data: messages,
            page: {
              has_more: false,
              oldest_seq: messages[0]?.seq ?? null,
              newest_seq: messages.at(-1)?.seq ?? null,
            },
          },
    );
  }

  it('shows the thread, marks it read and sends idempotently', async () => {
    mockParams = { id: 'c1' };
    serve(conversation({ read_through_seq: 1 }), [
      message('m1', 1, bo, 'Dinner?'),
      message('m2', 2, meSummary, 'See you at 8'),
      message('m3', 3, bo, 'Great'),
    ]);
    mockApi.put.mockResolvedValue({});
    mockApi.post.mockResolvedValue(message('m4', 4, meSummary, 'On my way'));
    await renderUi(<Chat />);
    expect(await screen.findByText('Dinner?')).toBeTruthy();
    expect(screen.getByText(/end-to-end encrypted/)).toBeTruthy();
    await waitFor(() =>
      expect(mockApi.put).toHaveBeenCalledWith('/v1/conversations/c1/receipts', {
        body: { read_through_seq: 3, delivered_through_seq: 3 },
      }),
    );

    await fireEvent.changeText(screen.getByTestId('chat-input'), '  On my way ');
    await fireEvent.press(screen.getByTestId('chat-send'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
        idempotencyKey: 'client-1',
        body: { client_message_id: 'client-1', body: 'On my way' },
      }),
    );
    expect(await screen.findByText('On my way')).toBeTruthy();
  });

  it('keeps a sent message when an older poll lands after it', async () => {
    mockParams = { id: 'c1' };
    const before = [message('m1', 1, bo, 'Dinner?')];
    serve(conversation({ read_through_seq: 1, last_seq: 1 }), before);
    mockApi.put.mockResolvedValue({});
    const client = testClient();
    await renderUi(<Chat />, client);
    expect(await screen.findByText('Dinner?')).toBeTruthy();

    // A poll starts and stays in flight with the list from before the send.
    let landPoll: (value: unknown) => void = () => undefined;
    mockApi.get.mockImplementation((path: string) =>
      path === '/v1/conversations/c1'
        ? Promise.resolve(conversation({ read_through_seq: 1, last_seq: 1 }))
        : new Promise((resolve) => {
            landPoll = resolve;
          }),
    );
    void client.refetchQueries({ queryKey: ['messages', 'history', 'c1'] });
    mockApi.post.mockResolvedValue(message('m2', 2, meSummary, 'Yes, 8pm'));
    await fireEvent.changeText(screen.getByTestId('chat-input'), 'Yes, 8pm');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByText('Yes, 8pm')).toBeTruthy();

    await act(async () => {
      landPoll({ data: before, page: { has_more: false, oldest_seq: 1, newest_seq: 1 } });
    });
    const kept = client.getQueryData<{ data: Message[] }>(['messages', 'history', 'c1']);
    expect(kept?.data.map((m) => m.id)).toEqual(['m1', 'm2']);
    expect(screen.getByText('Yes, 8pm')).toBeTruthy();
  });

  it('explains a message refused by the new-connection safety filter', async () => {
    mockParams = { id: 'c1' };
    serve(conversation({ read_through_seq: 1 }), [message('m1', 1, bo, 'Hi!')]);
    mockApi.put.mockResolvedValue({});
    mockApi.post.mockRejectedValue(
      new ApiProblem(
        {
          type: 'x',
          title: 'Unprocessable',
          status: 422,
          code: 'validation_failed',
          errors: [{ field: '/body', code: 'message_filtered', message: 'No.' }],
        },
        'r',
      ),
    );
    await renderUi(<Chat />);
    await fireEvent.changeText(await screen.findByTestId('chat-input'), 'gift card?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('chat-send-error')).toHaveTextContent(
      "This can't be sent to someone you just connected with. Keep it friendly.",
    );
  });

  it('shows read state reciprocally and tombstones', async () => {
    mockParams = { id: 'c1' };
    const deleted = { ...message('m1', 1, bo, null), deleted_at: '2026-11-09T10:01:00Z' };
    serve(conversation({ read_through_seq: 2, peer_read_through_seq: 2 }), [
      deleted,
      message('m2', 2, meSummary, 'See you at 8'),
    ]);
    await renderUi(<Chat />);
    expect(await screen.findByText('Message deleted')).toBeTruthy();
    const read = screen.getByTestId('message-read');
    expect(read).toHaveProp('accessibilityLabel', 'Read by Bo');
    expect(within(read).getByText('Read')).toBeTruthy();
  });

  it('explains why sending is unavailable after a block', async () => {
    mockParams = { id: 'c1' };
    serve(conversation({ can_send: false, send_restriction: 'blocked', read_through_seq: 2 }), [
      message('m2', 2, meSummary, 'See you at 8'),
    ]);
    await renderUi(<Chat />);
    expect(await screen.findByTestId('chat-restricted')).toHaveTextContent(
      'You blocked this person. Unblock them to send messages.',
    );
    expect(screen.queryByTestId('chat-input')).toBeNull();
  });

  it('deletes my message and reports theirs from the long-press menu', async () => {
    mockParams = { id: 'c1' };
    serve(conversation({ read_through_seq: 2 }), [
      message('m1', 1, bo, 'Spam link'),
      message('m2', 2, meSummary, 'Oops typo'),
    ]);
    mockApi.delete.mockResolvedValue(undefined);
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    await renderUi(<Chat />);
    await fireEvent(await screen.findByTestId('message-m2'), 'longPress');
    const mine = alert.mock.calls.at(-1)?.[2] ?? [];
    mine.find((button) => button.text === 'Delete for everyone')?.onPress?.();
    await waitFor(() =>
      expect(mockApi.delete).toHaveBeenCalledWith('/v1/conversations/c1/messages/m2'),
    );

    await fireEvent(screen.getByTestId('message-m1'), 'longPress');
    const theirs = alert.mock.calls.at(-1)?.[2] ?? [];
    theirs.find((button) => button.text === 'Report message')?.onPress?.();
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/report',
      params: { type: 'message', target: 'm1', name: 'Bo' },
    });
    alert.mockRestore();
  });
});

describe('profile', () => {
  it('opens the direct conversation with a connection', async () => {
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
            relationship: 'connected',
            can_request_connection: false,
            can_message: true,
          }
        : { data: [], page: { next_cursor: null, has_more: false } },
    );
    mockApi.post.mockResolvedValue(conversation());
    await renderUi(<UserProfile />);
    await fireEvent.press(await screen.findByTestId('user-message'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations', {
        body: { kind: 'direct', user_id: 'u2' },
      }),
    );
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: '/chat/[id]', params: { id: 'c1' } });
  });
});
