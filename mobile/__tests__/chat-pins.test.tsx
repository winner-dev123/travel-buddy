// req: DM-011, GCHAT-005, GCHAT-004
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Alert, type AlertButton } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Conversation, Message } from '@/features/messages/api';
import { i18n } from '@/i18n';

import Chat from '../app/chat/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => '00000000-0000-4000-8000-000000000001'),
};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
const mockUploadPhoto = jest.fn();
const mockPickPhotos = jest.fn();
jest.mock('@/features/media/upload', () => ({
  UnsupportedPhotoError: class extends Error {},
  pickPhotos: (...args: unknown[]) => mockPickPhotos(...args),
  takePhoto: jest.fn(),
  uploadPhoto: (...args: unknown[]) => mockUploadPhoto(...args),
}));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: 'c1' }),
  Stack: { Screen: () => null },
}));

const user = (id: string, name: string) => ({
  id,
  handle: name.toLowerCase(),
  display_name: name,
  avatar: null,
});
const bo = user('bo', 'Bo');
const meUser = user('u9', 'Me');

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

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 'c1',
    kind: 'direct',
    title: null,
    group_id: null,
    counterpart: bo,
    last_message: null,
    last_seq: 2,
    unread_count: 0,
    read_through_seq: 2,
    delivered_through_seq: 2,
    muted_until: null,
    notification_level: 'all',
    can_send: true,
    send_restriction: null,
    created_at: '2026-11-09T09:00:00Z',
    last_message_at: null,
    ...overrides,
  };
}

function message(
  id: string,
  seq: number,
  sender: typeof bo,
  body: string,
  extra: Partial<Message> = {},
): Message {
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
    ...extra,
  };
}

const page = (data: Message[]) => ({
  data,
  page: { has_more: false, oldest_seq: data[0]?.seq ?? null, newest_seq: data.at(-1)?.seq ?? null },
});

function serve(
  conv: Conversation,
  history: Message[],
  pins: Message[] = [],
  groupPermissions: string[] = [],
) {
  mockApi.get.mockImplementation(async (path: string) => {
    if (path === '/v1/conversations/c1') return conv;
    if (path === '/v1/conversations/c1/messages') return page(history);
    if (path === '/v1/conversations/c1/pins') return page(pins);
    if (path === '/v1/groups/g1')
      return {
        id: 'g1',
        my_membership: {
          role: 'member',
          status: 'active',
          permissions: groupPermissions,
          restricted_until: null,
        },
      };
    throw new Error(`unexpected ${path}`);
  });
}

async function renderChat() {
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
      <QueryClientProvider client={client}>
        <Chat />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

let buttons: AlertButton[] = [];

beforeEach(async () => {
  for (const fn of [mockApi.get, mockApi.post, mockApi.put, mockApi.delete]) fn.mockReset();
  buttons = [];
  mockApi.put.mockResolvedValue(undefined); // read marks and pins
  jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, given) => {
    buttons = given ?? [];
  });
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

afterEach(() => jest.restoreAllMocks());

const press = (label: string) => buttons.find((button) => button.text === label)?.onPress?.();

it('replies to a message and shows the quote', async () => {
  const hello = message('m1', 1, bo, 'Dinner at 8?');
  serve(conversation(), [
    hello,
    message('m2', 2, meUser, 'Sure', {
      reply_to: {
        id: 'm1',
        seq: 1,
        sender_id: 'bo',
        kind: 'text',
        snippet: 'Dinner at 8?',
        deleted: false,
        created_at: '',
      },
    }),
  ]);
  mockApi.post.mockResolvedValue(message('m3', 3, meUser, 'Where?'));
  await renderChat();
  expect(await screen.findByTestId('reply-quote-m2')).toHaveTextContent('↩ Dinner at 8?');

  await fireEvent(screen.getByTestId('message-m1'), 'longPress');
  press('Reply');
  expect(await screen.findByTestId('chat-replying')).toHaveTextContent(
    /^Replying to Bo: Dinner at 8\?/,
  );
  await fireEvent.changeText(screen.getByTestId('chat-input'), 'Where?');
  await fireEvent.press(screen.getByTestId('chat-send'));
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
      idempotencyKey: '00000000-0000-4000-8000-000000000001',
      body: {
        client_message_id: '00000000-0000-4000-8000-000000000001',
        body: 'Where?',
        reply_to_message_id: 'm1',
      },
    }),
  );
  await waitFor(() => expect(screen.queryByTestId('chat-replying')).toBeNull());
});

it('pins in a direct chat and lists pinned messages', async () => {
  const plan = message('m1', 1, bo, 'Meet at Rossio, 8pm', { pinned: true });
  serve(conversation(), [plan, message('m2', 2, bo, 'ok')], [plan]);
  mockApi.put.mockResolvedValue(undefined);
  mockApi.delete.mockResolvedValue(undefined);
  await renderChat();
  expect(await screen.findByTestId('chat-pins')).toHaveTextContent(
    '📌 1 pinned · Meet at Rossio, 8pm',
  );
  await fireEvent.press(screen.getByTestId('chat-pins-toggle'));
  await fireEvent.press(await screen.findByTestId('unpin-m1'));
  await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/conversations/c1/pins/m1'));

  await fireEvent(screen.getByTestId('message-m2'), 'longPress');
  press('Pin');
  await waitFor(() => expect(mockApi.put).toHaveBeenCalledWith('/v1/conversations/c1/pins/m2'));
});

it('offers pinning in a group chat only with the permission', async () => {
  serve(
    conversation({ kind: 'group', group_id: 'g1', counterpart: null, title: 'Supper club' }),
    [message('m1', 1, bo, 'hi')],
    [],
    [],
  );
  await renderChat();
  await screen.findByTestId('message-m1');
  await waitFor(() => expect(mockApi.get).toHaveBeenCalledWith('/v1/groups/g1'));
  await fireEvent(screen.getByTestId('message-m1'), 'longPress');
  expect(buttons.map((button) => button.text)).toEqual([
    'React',
    'Reply',
    'Report message',
    'Cancel',
  ]);
});

it.each([
  ['chat_admins_only', 'Only admins can post in this chat.'],
  [
    'member_restricted',
    "You can't post in this group for now. A group admin restricted your account here.",
  ],
  ['archived', 'This group is archived. Its chat is read-only.'],
  ['blocked', 'You blocked this person. Unblock them to send messages.'],
] as const)('explains why sending is off (%s)', async (restriction, text) => {
  serve(
    conversation({ kind: 'group', group_id: 'g1', can_send: false, send_restriction: restriction }),
    [],
  );
  await renderChat();
  expect(await screen.findByTestId('chat-restricted')).toHaveTextContent(text);
});

it('mutes a chat for a chosen time and unmutes it', async () => {
  serve(conversation(), [message('m1', 1, bo, 'hi')]);
  const muted = conversation({ muted_until: '2099-01-01T00:00:00Z' });
  mockApi.put.mockImplementation(
    async (path: string, options?: { body: { muted_until: string | null } }) =>
      path === '/v1/conversations/c1/mute'
        ? options?.body.muted_until
          ? muted
          : conversation()
        : undefined,
  );
  await renderChat();
  await fireEvent.press(await screen.findByTestId('chat-mute'));
  expect(buttons.map((b) => b.text)).toEqual(['For 1 hour', 'For 8 hours', 'For 1 week', 'Cancel']);
  const before = Date.now();
  press('For 8 hours');
  await waitFor(() =>
    expect(mockApi.put).toHaveBeenCalledWith('/v1/conversations/c1/mute', expect.anything()),
  );
  const call = mockApi.put.mock.calls.find(([path]) => path === '/v1/conversations/c1/mute');
  const until = Date.parse(call![1].body.muted_until);
  expect(until - before).toBeGreaterThanOrEqual(8 * 3_600_000 - 1000);
  expect(await screen.findByTestId('chat-muted')).toHaveTextContent(/^Muted until /);

  await fireEvent.press(screen.getByTestId('chat-mute')); // now "Unmute"
  await waitFor(() =>
    expect(mockApi.put).toHaveBeenLastCalledWith('/v1/conversations/c1/mute', {
      body: { muted_until: null },
    }),
  );
  await waitFor(() => expect(screen.queryByTestId('chat-muted')).toBeNull());
});

it('reacts to a message and toggles a reaction from its chip', async () => {
  const liked = message('m1', 1, bo, 'Rossio at 8', {
    reactions: [{ emoji: '👍', count: 2, reacted_by_me: true }],
  });
  serve(conversation(), [liked, message('m2', 2, bo, 'ok')]);
  mockApi.delete.mockResolvedValue(undefined);
  await renderChat();
  await fireEvent.press(await screen.findByTestId('reaction-m1-👍')); // mine: removes it
  await waitFor(() =>
    expect(mockApi.delete).toHaveBeenCalledWith(
      `/v1/conversations/c1/messages/m1/reactions/${encodeURIComponent('👍')}`,
    ),
  );
  await fireEvent(screen.getByTestId('message-m2'), 'longPress');
  press('React');
  expect(buttons.map((b) => b.text)).toEqual(['👍', '❤️', '😂', '😮', '🙏', '🎉', 'Cancel']);
  press('🎉');
  await waitFor(() =>
    expect(mockApi.put).toHaveBeenCalledWith(
      `/v1/conversations/c1/messages/m2/reactions/${encodeURIComponent('🎉')}`,
    ),
  );
});

it('clears the chat for me after confirming', async () => {
  serve(conversation(), [message('m1', 1, bo, 'hi'), message('m2', 2, bo, 'there')]);
  mockApi.post.mockResolvedValue(undefined);
  await renderChat();
  await fireEvent.press(await screen.findByTestId('chat-clear'));
  press('Clear');
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/clear', {
      body: { through_seq: 2 },
    }),
  );
});

it('sends a photo through the scanned upload flow (DM-002)', async () => {
  serve(conversation(), [message('m1', 1, bo, 'hi')]);
  mockPickPhotos.mockResolvedValue([
    { uri: 'file:///p.jpg', width: 800, height: 600, mimeType: 'image/jpeg' },
  ]);
  mockUploadPhoto.mockResolvedValue('media-1');
  mockApi.post.mockResolvedValue(
    message('m2', 2, meUser, '', {
      body: null as unknown as string,
      attachments: [{ id: 'media-1', kind: 'image', status: 'processing', url: null }],
    }),
  );
  await renderChat();
  await fireEvent.press(await screen.findByTestId('chat-photo'));
  press('Choose photos');
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
      idempotencyKey: '00000000-0000-4000-8000-000000000001',
      body: {
        client_message_id: '00000000-0000-4000-8000-000000000001',
        kind: 'image',
        attachment_media_ids: ['media-1'],
      },
    }),
  );
  expect(mockPickPhotos).toHaveBeenCalledWith(1);
  expect(mockUploadPhoto.mock.calls[0]?.[2]).toBe('message');
  expect(await screen.findByTestId('message-photos-m2')).toBeTruthy();
});

it('shows received photos instead of a placeholder', async () => {
  serve(conversation(), [
    message('m1', 1, bo, '', {
      body: null as unknown as string,
      attachments: [
        {
          id: 'a1',
          kind: 'image',
          status: 'ready',
          url: 'https://cdn.test/a1.webp',
          width: 800,
          height: 600,
        },
      ],
    }),
  ]);
  await renderChat();
  expect(await screen.findByTestId('message-photos-m1')).toBeTruthy();
  expect(screen.queryByText('Photo')).toBeNull();
});
