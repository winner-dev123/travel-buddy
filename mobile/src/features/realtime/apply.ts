import type { QueryClient } from '@tanstack/react-query';

import { accountKeys } from '@/features/account/api';
import {
  messageKeys,
  type Conversation,
  type Message,
  type MessageList,
} from '@/features/messages/api';

import type { ServerFrame } from './client';
import { useRealtimeStore } from './store';

/** A notification as `notification.new` carries it (mirrors `GET /v1/notifications`). */
export interface LiveNotification {
  id: string;
  type: string;
  actor: { id: string; handle: string; display_name: string } | null;
  entity_type: string | null;
  entity_id: string | null;
  title: string;
  body: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ApplyContext {
  queryClient: QueryClient;
  me: string | undefined;
  onNotification?: (notification: LiveNotification) => void;
  /** A message of mine was persisted (echoed with its client id). */
  onOwnMessage?: (clientMessageId: string, message: Message) => void;
  now?: () => number;
}

/**
 * Insert or replace a message in the cached history; refetch when a gap shows up (docs/06 §6).
 * A poll already in flight would land with a list from before this message and hide it, so it is
 * cancelled first (the next one includes the message anyway).
 */
export function upsertMessage(queryClient: QueryClient, message: Message): void {
  const key = messageKeys.history(message.conversation_id);
  if (!queryClient.getQueryData<MessageList>(key)) return; // not cached: loads fresh when opened
  if (queryClient.isFetching({ queryKey: key }) > 0) {
    void queryClient.cancelQueries({ queryKey: key }).then(() => insert(queryClient, message));
  } else {
    insert(queryClient, message);
  }
}

function insert(queryClient: QueryClient, message: Message): void {
  const key = messageKeys.history(message.conversation_id);
  const old = queryClient.getQueryData<MessageList>(key);
  if (!old) return;
  const index = old.data.findIndex((m) => m.id === message.id);
  if (index >= 0) {
    const data = [...old.data];
    data[index] = message;
    queryClient.setQueryData<MessageList>(key, { ...old, data });
    return;
  }
  const newest = old.page.newest_seq ?? 0;
  if (newest > 0 && message.seq > newest + 1) {
    void queryClient.invalidateQueries({ queryKey: key }); // missed some: catch up over REST
    return;
  }
  const data = [...old.data, message].sort((a, b) => a.seq - b.seq);
  queryClient.setQueryData<MessageList>(key, {
    data,
    page: {
      ...old.page,
      newest_seq: Math.max(newest, message.seq),
      oldest_seq: old.page.oldest_seq ?? message.seq,
    },
  });
}

/** Apply one server frame to the cached data and the realtime store. */
export function applyFrame(frame: ServerFrame, context: ApplyContext): void {
  const { queryClient, me } = context;
  const data = frame.data ?? {};
  const now = (context.now ?? Date.now)();
  switch (frame.type) {
    case 'message.new': {
      const message = data.message as Message | undefined;
      if (!message) return;
      upsertMessage(queryClient, message);
      if (message.sender?.id) {
        useRealtimeStore.getState().setTyping(message.conversation_id, message.sender.id, null);
      }
      if (message.client_message_id && message.sender?.id === me) {
        context.onOwnMessage?.(message.client_message_id, message);
      }
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
      return;
    }
    case 'message.updated': {
      const message = data.message as Message | undefined;
      if (message) upsertMessage(queryClient, message);
      return;
    }
    case 'message.deleted': {
      const conversationId = String(data.conversation_id ?? '');
      const key = messageKeys.history(conversationId);
      const old = queryClient.getQueryData<MessageList>(key);
      if (old) {
        queryClient.setQueryData<MessageList>(key, {
          ...old,
          data: old.data.map((m) =>
            m.id === data.message_id
              ? {
                  ...m,
                  deleted_at: String(data.deleted_at ?? new Date(now).toISOString()),
                  body: null,
                  attachments: [],
                }
              : m,
          ),
        });
      }
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
      return;
    }
    case 'receipt.updated': {
      if (data.user_id === me) return;
      const conversationId = String(data.conversation_id ?? '');
      queryClient.setQueryData<Conversation>(messageKeys.conversation(conversationId), (old) => {
        if (!old) return old;
        const read = typeof data.read_through_seq === 'number' ? data.read_through_seq : null;
        const delivered =
          typeof data.delivered_through_seq === 'number' ? data.delivered_through_seq : null;
        return {
          ...old,
          peer_read_through_seq:
            read === null
              ? old.peer_read_through_seq
              : Math.max(old.peer_read_through_seq ?? 0, read),
          peer_delivered_through_seq:
            delivered === null
              ? old.peer_delivered_through_seq
              : Math.max(old.peer_delivered_through_seq ?? 0, delivered),
        };
      });
      return;
    }
    case 'typing': {
      const conversationId = String(data.conversation_id ?? '');
      const userId = String(data.user_id ?? '');
      if (!conversationId || !userId || userId === me) return;
      const until =
        data.state === 'started' ? Date.parse(String(data.expires_at ?? '')) || now + 8000 : null;
      useRealtimeStore.getState().setTyping(conversationId, userId, until);
      return;
    }
    case 'conversation.updated':
    case 'membership.changed': {
      const conversationId = String(data.conversation_id ?? '');
      if (conversationId) {
        void queryClient.invalidateQueries({ queryKey: messageKeys.conversation(conversationId) });
      }
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
      return;
    }
    case 'sync.required': {
      if (data.full_resync) {
        void queryClient.invalidateQueries({ queryKey: ['messages'] });
        return;
      }
      for (const item of (data.conversations as { conversation_id: string }[] | undefined) ?? []) {
        void queryClient.invalidateQueries({ queryKey: messageKeys.history(item.conversation_id) });
      }
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
      return;
    }
    case 'notification.new': {
      const notification = data.notification as LiveNotification | undefined;
      void queryClient.invalidateQueries({ queryKey: accountKeys.notifications });
      if (
        notification?.type === 'connection_request' ||
        notification?.type === 'connection_accepted'
      ) {
        void queryClient.invalidateQueries({ queryKey: accountKeys.requests('incoming') });
        void queryClient.invalidateQueries({ queryKey: accountKeys.connections });
      }
      if (notification) context.onNotification?.(notification);
      return;
    }
    default:
      return;
  }
}

/** What to ask the server after (re)connecting: the newest seq held per cached conversation. */
export function syncRequest(
  queryClient: QueryClient,
): { conversation_id: string; last_seq: number }[] {
  return queryClient
    .getQueriesData<MessageList>({ queryKey: ['messages', 'history'] })
    .flatMap(([key, list]) => {
      const conversationId = String(key[2] ?? '');
      const newest = list?.page.newest_seq;
      return conversationId && typeof newest === 'number'
        ? [{ conversation_id: conversationId, last_seq: newest }]
        : [];
    })
    .slice(0, 500);
}
