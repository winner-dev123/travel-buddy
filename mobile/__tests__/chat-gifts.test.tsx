// req: DM-016
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiNetworkError, ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import {
  messageKeys,
  type Conversation,
  type Message,
  type MessageList,
} from '@/features/messages/api';
import { useOutboxStore } from '@/features/messages/outbox';
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

function message(id: string, seq: number, sender: typeof bo, overrides: Partial<Message> = {}) {
  return {
    id,
    conversation_id: 'c1',
    seq,
    sender,
    kind: 'text',
    body: 'Hi!',
    gift: null,
    attachments: [],
    reply_to: null,
    reactions: [],
    pinned: false,
    moderation_state: 'visible',
    edited_at: null,
    deleted_at: null,
    created_at: '2026-11-09T10:00:00Z',
    ...overrides,
  } satisfies Message as Message;
}

function gift(id: string, seq: number, sender: typeof bo, openedAt: string | null = null) {
  return message(id, seq, sender, {
    kind: 'gift',
    body: null,
    gift: { code: 'coffee', opened_at: openedAt },
  });
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

function fakeSocket(reply: (type: string, data: Record<string, unknown>) => ServerFrame) {
  const sent: { type: string; data: Record<string, unknown> }[] = [];
  const socket = {
    isOnline: true,
    send: jest.fn((type: string, data: Record<string, unknown>) => {
      sent.push({ type, data });
      return true;
    }),
    request: jest.fn(async (type: string, data: Record<string, unknown>) => {
      sent.push({ type, data });
      return reply(type, data);
    }),
  };
  realtimeHandle.current = socket as unknown as RealtimeClient;
  return sent;
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

describe('emoji and gifts panel', () => {
  it('opens beside the field and adds emoji to the message', async () => {
    serve(conversation(), [message('m1', 1, bo)]);
    await renderUi(<Chat />);
    await screen.findByText('Hi!');
    expect(screen.queryByTestId('expression-tray')).toBeNull();

    await fireEvent.press(screen.getByTestId('chat-tray'));
    expect(screen.getByTestId('expression-tray')).toBeTruthy();
    expect(screen.getByTestId('tray-tab-emoji')).toBeSelected();
    await fireEvent.press(screen.getByTestId('emoji-😀'));
    await fireEvent.press(screen.getByTestId('emoji-✈️'));
    expect(screen.getByTestId('chat-input').props.value).toBe('😀✈️');
    expect(screen.getByTestId('chat-send')).toBeEnabled();

    // Typing again brings the keyboard back instead of the panel.
    await fireEvent(screen.getByTestId('chat-input'), 'focus');
    expect(screen.queryByTestId('expression-tray')).toBeNull();
  });

  it('sends a chosen gift over the socket and shows it to me open', async () => {
    const sent = fakeSocket((_type, data) => ({
      v: 1,
      type: 'message.ack',
      id: 'f1',
      data: { message_id: 'm2', seq: 2, client_message_id: data.client_message_id },
    }));
    serve(conversation(), [message('m1', 1, bo)]);
    await renderUi(<Chat />);
    await screen.findByText('Hi!');

    await fireEvent.press(screen.getByTestId('chat-tray'));
    await fireEvent.press(screen.getByTestId('tray-tab-gifts'));
    expect(screen.getByTestId('gift-send')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('gift-snow_globe'));
    await fireEvent.press(screen.getByTestId('gift-coffee'));
    expect(screen.getByTestId('gift-coffee')).toBeSelected();
    expect(screen.getByTestId('gift-snow_globe')).not.toBeSelected();
    await fireEvent.press(screen.getByTestId('gift-send'));

    await waitFor(() =>
      expect(sent).toContainEqual({
        type: 'message.send',
        data: {
          conversation_id: 'c1',
          client_message_id: 'client-1',
          kind: 'gift',
          gift: 'coffee',
        },
      }),
    );
    const bubble = await screen.findByTestId('message-m2');
    expect(bubble).toHaveProp('accessibilityLabel', 'You sent: Coffee');
    expect(screen.getByTestId('gift-status-m2')).toHaveTextContent('Not opened yet');
    expect(screen.queryByTestId('expression-tray')).toBeNull();
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it('shows a gift at once while offline and sends it over REST when it can', async () => {
    serve(conversation(), [message('m1', 1, bo)]);
    mockApi.post.mockRejectedValue(new ApiNetworkError('offline', 'r1'));
    await renderUi(<Chat />);
    await screen.findByText('Hi!');

    await fireEvent.press(screen.getByTestId('chat-tray'));
    await fireEvent.press(screen.getByTestId('tray-tab-gifts'));
    await fireEvent.press(screen.getByTestId('gift-cake'));
    await fireEvent.press(screen.getByTestId('gift-send'));

    expect(await screen.findByTestId('queued-client-1')).toHaveProp(
      'accessibilityLabel',
      'You sent: Cake',
    );
    expect(screen.getByTestId('queued-status-client-1')).toHaveTextContent('Sending…');
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
        idempotencyKey: 'client-1',
        body: { client_message_id: 'client-1', kind: 'gift', gift: 'cake' },
      }),
    );
    expect(useOutboxStore.getState().items).toEqual([
      expect.objectContaining({ clientMessageId: 'client-1', gift: 'cake', body: '' }),
    ]);
  });

  it('offers only emoji in group chats', async () => {
    serve(conversation({ kind: 'group', counterpart: null, title: 'Lisbon crew' }), [
      message('m1', 1, bo),
    ]);
    await renderUi(<Chat />);
    await screen.findByText('Hi!');
    await fireEvent.press(screen.getByTestId('chat-tray'));
    expect(screen.getByTestId('emoji-😀')).toBeTruthy();
    expect(screen.queryByTestId('tray-tab-gifts')).toBeNull();
    expect(screen.queryByTestId('gift-coffee')).toBeNull();
  });
});

describe('receiving a gift', () => {
  it('arrives wrapped and opens with a tap', async () => {
    serve(conversation(), [gift('g1', 1, bo)]);
    mockApi.post.mockResolvedValue(gift('g1', 1, bo, '2026-11-12T10:00:00Z'));
    await renderUi(<Chat />);

    const wrapped = await screen.findByTestId('message-g1');
    expect(wrapped).toHaveProp('accessibilityLabel', 'Gift from Bo, still wrapped. Open it.');
    expect(wrapped).toHaveTextContent(/Bo sent you a gift.*Tap to open/);
    await fireEvent.press(wrapped);

    expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/messages/g1/gift/open');
    await waitFor(() =>
      expect(screen.getByTestId('message-g1')).toHaveProp('accessibilityLabel', 'Gift: Coffee'),
    );
    expect(screen.getByTestId('message-g1')).toHaveTextContent('Coffee');
    expect(screen.queryByText('Tap to open')).toBeNull();
  });

  it('puts the bow back when the gift cannot be opened', async () => {
    serve(conversation(), [gift('g1', 1, bo)]);
    mockApi.post.mockRejectedValue(
      new ApiProblem({ type: 'x', title: 'Forbidden', status: 403, code: 'forbidden' }, 'r'),
    );
    await renderUi(<Chat />);
    await fireEvent.press(await screen.findByTestId('message-g1'));

    expect(await screen.findByTestId('gift-open-failed')).toHaveTextContent(
      "The gift couldn't be opened. Try again.",
    );
    expect(screen.getByTestId('message-g1')).toHaveProp(
      'accessibilityLabel',
      'Gift from Bo, still wrapped. Open it.',
    );
  });

  it('tells the sender once it has been opened', async () => {
    const client = testClient();
    serve(conversation(), [message('m1', 1, bo), gift('g2', 2, meSummary)]);
    await renderUi(<Chat />, client);
    expect(await screen.findByTestId('gift-status-g2')).toHaveTextContent('Not opened yet');
    expect(screen.getByTestId('message-g2')).toHaveProp('accessibilityLabel', 'You sent: Coffee');

    // What a `message.updated` (change `gift_opened`) frame does to the cached history.
    await act(async () => {
      client.setQueryData<MessageList>(messageKeys.history('c1'), (old) =>
        old
          ? {
              ...old,
              data: old.data.map((m) =>
                m.id === 'g2' ? gift('g2', 2, meSummary, '2026-11-12T10:00:00Z') : m,
              ),
            }
          : old,
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByTestId('gift-status-g2')).toHaveTextContent('Opened');
  });
});
