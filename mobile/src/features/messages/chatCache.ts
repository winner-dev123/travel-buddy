import type { QueryClient } from '@tanstack/react-query';
import { File, Paths } from 'expo-file-system';

import { onSessionEnded } from '@/auth/deviceSession';
import { useSessionStore } from '@/auth/sessionStore';
import type { Page } from '@/features/feed/types';

import { messageKeys, type Conversation, type MessageList } from './api';

/**
 * Recent chats kept on the device (ADR-0033), so the inbox and the last conversations open
 * without a network, including right after a restart. Written a moment after the cached data
 * changes, read once at startup, and deleted when the session ends. The cached data is shown as
 * stale, so it refreshes as soon as a connection allows.
 */

const MAX_CONVERSATIONS = 30;
const MAX_MESSAGES = 60;
const WRITE_DELAY_MS = 2_000;

interface SavedChats {
  version: 1;
  account: string;
  savedAt: number;
  inbox: Page<Conversation> | null;
  conversations: Record<string, { conversation: Conversation | null; history: MessageList | null }>;
}

const cacheFile = () => new File(Paths.document, 'chat-cache.json');

onSessionEnded(() => {
  const file = cacheFile();
  if (file.exists) file.delete();
});

/** The newest messages of a history, marked as having more when trimmed. */
function trimmed(history: MessageList): MessageList {
  if (history.data.length <= MAX_MESSAGES) return history;
  const data = history.data.slice(-MAX_MESSAGES);
  return { data, page: { ...history.page, has_more: true, oldest_seq: data[0]?.seq ?? null } };
}

function readSaved(): SavedChats | null {
  try {
    const file = cacheFile();
    if (!file.exists) return null;
    const saved = JSON.parse(file.textSync()) as SavedChats;
    return saved?.version === 1 ? saved : null;
  } catch {
    return null;
  }
}

/**
 * What would be written now (null when nobody is signed in): the chats in memory, newest first,
 * then those saved before that are no longer in memory (unopened chats are dropped from memory
 * after a few minutes but stay saved).
 */
export function snapshotChats(
  queryClient: QueryClient,
  previous: SavedChats | null = null,
  now: number = Date.now(),
): SavedChats | null {
  const account = useSessionStore.getState().me?.account.id;
  if (!account) return null;
  const earlier = previous?.account === account ? previous : null;
  const histories = queryClient
    .getQueriesData<MessageList>({ queryKey: ['messages', 'history'] })
    .filter(([, data]) => data)
    .map(([key, data]) => ({
      id: String(key[2]),
      data: data as MessageList,
      at: queryClient.getQueryState(key)?.dataUpdatedAt ?? 0,
    }))
    .sort((a, b) => b.at - a.at);
  const conversations: SavedChats['conversations'] = {};
  for (const { id, data } of histories.slice(0, MAX_CONVERSATIONS)) {
    conversations[id] = {
      conversation: queryClient.getQueryData<Conversation>(messageKeys.conversation(id)) ?? null,
      history: trimmed(data),
    };
  }
  for (const [id, entry] of Object.entries(earlier?.conversations ?? {})) {
    if (Object.keys(conversations).length >= MAX_CONVERSATIONS) break;
    conversations[id] ??= entry;
  }
  return {
    version: 1,
    account,
    savedAt: now,
    inbox:
      queryClient.getQueryData<Page<Conversation>>(messageKeys.inbox) ?? earlier?.inbox ?? null,
    conversations,
  };
}

/** Put the chats saved by the last run back into the query cache (call once at startup). */
export function hydrateChatCache(queryClient: QueryClient): void {
  try {
    const saved = readSaved();
    if (!saved) return;
    // Marked as old as it is, so every screen refreshes it when it can.
    const options = { updatedAt: saved.savedAt };
    if (saved.inbox) queryClient.setQueryData(messageKeys.inbox, saved.inbox, options);
    for (const [id, entry] of Object.entries(saved.conversations ?? {})) {
      if (entry.conversation) {
        queryClient.setQueryData(messageKeys.conversation(id), entry.conversation, options);
      }
      if (entry.history) queryClient.setQueryData(messageKeys.history(id), entry.history, options);
    }
  } catch {
    // Unreadable cache: chats load from the network as usual.
  }
}

/** Save chats a moment after they change while signed in. Returns the unsubscribe function. */
export function persistChatCache(queryClient: QueryClient): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const write = () => {
    timer = null;
    const snapshot = snapshotChats(queryClient, readSaved());
    if (!snapshot || useSessionStore.getState().status !== 'signed_in') return;
    try {
      cacheFile().writeSync(JSON.stringify(snapshot));
    } catch {
      // Nothing kept this time; the next change tries again.
    }
  };
  const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated' || event.query.queryKey[0] !== 'messages' || timer) return;
    timer = setTimeout(write, WRITE_DELAY_MS);
  });
  return () => {
    unsubscribe();
    if (timer) clearTimeout(timer);
  };
}

/** A cache hydrated for a session that turns out not to exist must not stay in memory. */
export function forgetCachedChats(queryClient: QueryClient): void {
  queryClient.removeQueries({ queryKey: ['messages'] });
}
