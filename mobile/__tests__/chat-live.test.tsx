// req: DM-005, DM-007, DM-008, DM-014, DM-015
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Alert } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiNetworkError, ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Conversation, Message } from '@/features/messages/api';
import { sendQueuedMessages, useOutboxStore } from '@/features/messages/outbox';
import type { RealtimeClient, ServerFrame } from '@/features/realtime/client';
import { realtimeHandle } from '@/features/realtime/handle';
import { useRealtimeStore } from '@/features/realtime/store';
import { i18n } from '@/i18n';
import { DEFAULT_CHAT_PREFERENCES, useChatPreferences } from '@/state/chatPreferences';

import Chat from '../app/chat/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'client-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({ id: 'c1' }),
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

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 'c1',
    kind: 'direct',
    title: null,
    counterpart: bo,
    last_message: null,
    last_seq: 1,
    unread_count: 0,
    read_through_seq: 1,
    delivered_through_seq: 1,
    peer_read_through_seq: 0,
    peer_delivered_through_seq: 0,
    muted_until: null,
    notification_level: 'all',
    can_send: true,
    send_restriction: null,
    created_at: '2026-11-09T09:00:00Z',
    last_message_at: null,
    ...overrides,
  };
}

function message(id: string, seq: number, sender: typeof bo, body: string): Message {
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

function serve(convo: Conversation, messages: Message[]) {
  mockApi.get.mockImplementation(async (path: string) =>
    path === '/v1/conversations/c1'
      ? convo
      : path === '/v1/conversations/c1/pins'
        ? { data: [] }
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

/** A connected realtime client: `send` records frames, `request` answers with `reply`. */
function fakeSocket(reply?: (type: string, data: Record<string, unknown>) => ServerFrame) {
  const sent: { type: string; data: Record<string, unknown> }[] = [];
  const socket = {
    isOnline: true,
    send: jest.fn((type: string, data: Record<string, unknown>) => {
      sent.push({ type, data });
      return true;
    }),
    request: jest.fn(async (type: string, data: Record<string, unknown>) => {
      sent.push({ type, data });
      if (!reply) throw new Error('no reply');
      return reply(type, data);
    }),
  };
  realtimeHandle.current = socket as unknown as RealtimeClient;
  return { socket, sent };
}

/** testIDs of a host element's direct children, in order. */
function childIds(element: { children: unknown[] }): string[] {
  return element.children.map((child) =>
    typeof child === 'string'
      ? child
      : String((child as { props: { testID?: string } }).props.testID),
  );
}

beforeEach(async () => {
  jest.clearAllMocks();
  useSessionStore.getState().setSignedIn(me);
  useOutboxStore.setState({ items: [] });
  useRealtimeStore.setState({ status: 'idle', typing: {} });
  useChatPreferences.setState({ ...DEFAULT_CHAT_PREFERENCES });
  realtimeHandle.current = null;
  mockApi.put.mockResolvedValue({});
  await i18n.changeLanguage('en');
});

describe('composer', () => {
  it('puts the send button on the right of the message box, or on the left for left hands', async () => {
    serve(conversation(), [message('m1', 1, bo, 'Hi!')]);
    await renderUi(<Chat />);
    expect(childIds(await screen.findByTestId('chat-composer'))).toEqual([
      'chat-photo',
      'chat-input',
      'chat-send',
    ]);

    await act(async () => {
      useChatPreferences.setState({ sendSide: 'left' });
    });
    expect(childIds(screen.getByTestId('chat-composer'))).toEqual([
      'chat-send',
      'chat-input',
      'chat-photo',
    ]);
  });

  it('shows the chosen background behind the messages', async () => {
    serve(conversation(), [message('m1', 1, bo, 'Hi!')]);
    await renderUi(<Chat />);
    await screen.findByText('Hi!');
    expect(screen.queryByTestId('chat-background')).toBeNull();
    await act(async () => {
      useChatPreferences.setState({ background: { kind: 'builtin', id: 'coast' } });
    });
    expect(screen.getByTestId('chat-background')).toBeTruthy();
  });
});

describe('live connection', () => {
  it('sends over the socket, waits for the ack and shows the message without REST', async () => {
    const { sent } = fakeSocket((type, data) => ({
      v: 1,
      type: 'message.ack',
      id: 'f1',
      data: { message_id: 'm2', seq: 2, client_message_id: data.client_message_id },
    }));
    serve(conversation(), [message('m1', 1, bo, 'Dinner?')]);
    await renderUi(<Chat />);
    await screen.findByText('Dinner?');

    await fireEvent.changeText(screen.getByTestId('chat-input'), 'Yes!');
    expect(sent).toContainEqual({ type: 'typing.start', data: { conversation_id: 'c1' } });
    await fireEvent.press(screen.getByTestId('chat-send'));

    await waitFor(() =>
      expect(sent).toContainEqual({
        type: 'message.send',
        data: { conversation_id: 'c1', client_message_id: 'client-1', body: 'Yes!' },
      }),
    );
    expect(sent).toContainEqual({ type: 'typing.stop', data: { conversation_id: 'c1' } });
    expect(await screen.findByTestId('message-m2')).toHaveTextContent('Yes!');
    expect(screen.getByTestId('message-sent')).toHaveTextContent('Sent');
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(useOutboxStore.getState().items).toEqual([]);
  });

  it('marks the chat read over the socket instead of REST', async () => {
    const { sent } = fakeSocket();
    serve(conversation({ read_through_seq: 1 }), [
      message('m1', 1, bo, 'Dinner?'),
      message('m2', 2, bo, 'At 8?'),
    ]);
    await renderUi(<Chat />);
    await screen.findByText('At 8?');
    await waitFor(() =>
      expect(sent).toContainEqual({
        type: 'receipt.read',
        data: { conversation_id: 'c1', read_through_seq: 2 },
      }),
    );
    expect(mockApi.put).not.toHaveBeenCalled();
  });

  it('shows who is typing', async () => {
    serve(conversation(), [message('m1', 1, bo, 'Dinner?')]);
    await renderUi(<Chat />);
    await screen.findByText('Dinner?');
    expect(screen.queryByTestId('chat-typing')).toBeNull();

    await act(async () => {
      useRealtimeStore.getState().setTyping('c1', 'u2', Date.now() + 8000);
    });
    expect(screen.getByTestId('chat-typing')).toHaveTextContent('Bo is typing…');

    await act(async () => {
      useRealtimeStore.getState().setTyping('c1', 'u2', null);
    });
    expect(screen.queryByTestId('chat-typing')).toBeNull();
  });

  it("shows the reader's avatar next to Read once they've seen my message", async () => {
    const client = testClient();
    serve(conversation({ read_through_seq: 2, peer_read_through_seq: 1, last_seq: 2 }), [
      message('m1', 1, bo, 'Dinner?'),
      message('m2', 2, meSummary, 'See you at 8'),
    ]);
    await renderUi(<Chat />, client);
    expect(await screen.findByTestId('message-sent')).toHaveTextContent('Sent');
    await waitFor(() =>
      expect(client.getQueryData(['messages', 'conversation', 'c1'])).toBeDefined(),
    );

    // receipt.updated patches the cached conversation.
    await act(async () => {
      client.setQueryData<Conversation>(['messages', 'conversation', 'c1'], (old) =>
        old ? { ...old, peer_read_through_seq: 2 } : old,
      );
      await new Promise((resolve) => setTimeout(resolve, 0)); // TanStack notifies on a tick
    });
    const read = await screen.findByTestId('message-read');
    expect(read).toHaveProp('accessibilityLabel', 'Read by Bo');
    expect(within(read).getByText('Read')).toBeTruthy();
    // Bo's avatar: the initial, as Bo has no photo (decorative, so hidden from screen readers).
    expect(within(read).getByText('B', { includeHiddenElements: true })).toBeTruthy();
    expect(screen.queryByTestId('message-sent')).toBeNull();
  });
});

describe('poor network', () => {
  it('shows a message at once while offline and sends it when the network is back', async () => {
    const client = testClient();
    serve(conversation(), [message('m1', 1, bo, 'Dinner?')]);
    mockApi.post.mockRejectedValue(new ApiNetworkError('offline', 'r1'));
    await renderUi(<Chat />, client);
    await screen.findByText('Dinner?');

    await fireEvent.changeText(screen.getByTestId('chat-input'), 'On my way');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('queued-client-1')).toHaveTextContent('On my way');
    expect(screen.getByTestId('queued-status-client-1')).toHaveTextContent('Sending…');
    expect(screen.getByTestId('chat-input').props.value).toBe('');
    await waitFor(() => expect(mockApi.post).toHaveBeenCalledTimes(1));
    expect(useOutboxStore.getState().items).toEqual([
      expect.objectContaining({ clientMessageId: 'client-1', status: 'sending', attempts: 1 }),
    ]);

    // Back online: the same client_message_id goes out again (no duplicate on the server).
    mockApi.post.mockResolvedValue(message('m2', 2, meSummary, 'On my way'));
    useOutboxStore.setState({
      items: useOutboxStore.getState().items.map((item) => ({ ...item, nextAttemptAt: 0 })),
    });
    await act(async () => {
      await sendQueuedMessages(client);
    });
    expect(mockApi.post).toHaveBeenLastCalledWith('/v1/conversations/c1/messages', {
      idempotencyKey: 'client-1',
      body: { client_message_id: 'client-1', body: 'On my way' },
    });
    expect(await screen.findByTestId('message-m2')).toHaveTextContent('On my way');
    expect(screen.queryByTestId('queued-client-1')).toBeNull();
  });

  it('keeps a refused message with its reason and lets me retry or delete it', async () => {
    serve(conversation(), [message('m1', 1, bo, 'Hi!')]);
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
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    await renderUi(<Chat />);
    await fireEvent.changeText(await screen.findByTestId('chat-input'), 'gift card?');
    await fireEvent.press(screen.getByTestId('chat-send'));
    expect(await screen.findByTestId('queued-status-client-1')).toHaveTextContent(
      'Not sent · Tap for options',
    );
    expect(screen.getByTestId('chat-send-error')).toHaveTextContent(
      "This can't be sent to someone you just connected with. Keep it friendly.",
    );

    await fireEvent.press(screen.getByTestId('queued-client-1'));
    const buttons = alert.mock.calls.at(-1)?.[2] ?? [];
    expect(buttons.map((button) => button.text)).toEqual(['Try again', 'Delete message', 'Cancel']);
    await act(async () => {
      buttons.find((button) => button.text === 'Delete message')?.onPress?.();
    });
    expect(screen.queryByTestId('queued-client-1')).toBeNull();
    expect(screen.queryByTestId('chat-send-error')).toBeNull();
    alert.mockRestore();
  });
});
