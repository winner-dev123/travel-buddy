// req: DM-014
import { QueryClient } from '@tanstack/react-query';

import { endDeviceSession } from '@/auth/deviceSession';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';

import type { Conversation, Message, MessageList } from '../api';
import { hydrateChatCache, persistChatCache, snapshotChats } from '../chatCache';

jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const name = (part: unknown) => (typeof part === 'string' ? part : 'doc');
  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts.map(name).join('/');
    }
    get exists() {
      return files.has(this.uri);
    }
    textSync() {
      return files.get(this.uri) ?? '';
    }
    writeSync(text: string) {
      files.set(this.uri, text);
    }
    delete() {
      files.delete(this.uri);
    }
  }
  return { File, Paths: { document: {} }, mockFiles: files };
});

const fs = jest.requireMock<{ mockFiles: Map<string, string> }>('expo-file-system');
const CACHE = 'doc/chat-cache.json';

const me = {
  account: { id: 'u9' },
  profile: { id: 'u9', handle: 'me', display_name: 'Me' },
} as unknown as Me;

function messages(conversationId: string, count: number): MessageList {
  const data = Array.from(
    { length: count },
    (_, i) =>
      ({
        id: `${conversationId}-m${i + 1}`,
        conversation_id: conversationId,
        seq: i + 1,
      }) as Message,
  );
  return { data, page: { has_more: false, oldest_seq: 1, newest_seq: count } };
}

function client() {
  return new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
}

beforeEach(() => {
  fs.mockFiles.clear();
  useSessionStore.getState().setSignedIn(me);
});

it('keeps recent chats on the device and puts them back after a restart, as stale data', () => {
  const before = client();
  before.setQueryData(['messages', 'inbox'], { data: [{ id: 'c1' }], page: {} });
  before.setQueryData(['messages', 'conversation', 'c1'], { id: 'c1' } as Conversation);
  before.setQueryData(['messages', 'history', 'c1'], messages('c1', 3));
  const snapshot = snapshotChats(before, null, 1_000);
  fs.mockFiles.set(CACHE, JSON.stringify(snapshot));

  const after = client();
  hydrateChatCache(after);
  expect(after.getQueryData(['messages', 'inbox'])).toEqual({ data: [{ id: 'c1' }], page: {} });
  expect(after.getQueryData(['messages', 'conversation', 'c1'])).toEqual({ id: 'c1' });
  expect(after.getQueryData<MessageList>(['messages', 'history', 'c1'])?.data).toHaveLength(3);
  // Saved long ago: every screen refreshes it as soon as it can.
  expect(after.getQueryState(['messages', 'history', 'c1'])?.dataUpdatedAt).toBe(1_000);
});

it('keeps only the newest messages of each chat', () => {
  const queryClient = client();
  queryClient.setQueryData(['messages', 'history', 'c1'], messages('c1', 100));
  const saved = snapshotChats(queryClient)?.conversations.c1?.history;
  expect(saved?.data).toHaveLength(60);
  expect(saved?.data[0]?.seq).toBe(41);
  expect(saved?.page).toMatchObject({ has_more: true, oldest_seq: 41, newest_seq: 100 });
});

it('keeps chats saved earlier that are no longer in memory', () => {
  const first = client();
  first.setQueryData(['messages', 'history', 'c1'], messages('c1', 2));
  const earlier = snapshotChats(first);

  const later = client();
  later.setQueryData(['messages', 'history', 'c2'], messages('c2', 2));
  expect(Object.keys(snapshotChats(later, earlier)?.conversations ?? {})).toEqual(['c2', 'c1']);

  // Never another account's.
  useSessionStore.getState().setSignedIn({ ...me, account: { id: 'u5' } } as unknown as Me);
  expect(Object.keys(snapshotChats(later, earlier)?.conversations ?? {})).toEqual(['c2']);
});

it('writes a moment after chats change, and the file goes when the session ends', () => {
  jest.useFakeTimers();
  try {
    const queryClient = client();
    const stop = persistChatCache(queryClient);
    queryClient.setQueryData(['messages', 'history', 'c1'], messages('c1', 1));
    expect(fs.mockFiles.has(CACHE)).toBe(false);
    jest.advanceTimersByTime(2_000);
    expect(JSON.parse(fs.mockFiles.get(CACHE) ?? '{}').account).toBe('u9');
    stop();

    endDeviceSession();
    expect(fs.mockFiles.has(CACHE)).toBe(false);
  } finally {
    jest.useRealTimers();
  }
});

it('writes nothing while signed out', () => {
  useSessionStore.getState().setSignedOut();
  const queryClient = client();
  queryClient.setQueryData(['messages', 'history', 'c1'], messages('c1', 1));
  expect(snapshotChats(queryClient)).toBeNull();
});
