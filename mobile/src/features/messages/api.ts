import type { ApiClient } from '@/api';
import type { MediaRef, Page, UserSummary } from '@/features/feed/types';

import type { GiftCode } from './gifts';

/** Contract `MessagePreview`. */
export interface MessagePreview {
  id: string;
  seq: number;
  sender_id: string | null;
  kind: 'text' | 'image' | 'system' | 'announcement' | 'gift';
  snippet: string | null;
  deleted: boolean;
  created_at: string;
}

export type SendRestriction =
  'connection_required' | 'blocked' | 'member_restricted' | 'chat_admins_only' | 'archived';

/** Contract `Conversation`. */
export interface Conversation {
  id: string;
  kind: 'direct' | 'group' | 'challenge_team';
  title: string | null;
  group_id?: string | null;
  counterpart: UserSummary | null;
  last_message: MessagePreview | null;
  last_seq: number;
  unread_count: number;
  read_through_seq: number;
  delivered_through_seq: number;
  peer_read_through_seq?: number | null;
  peer_delivered_through_seq?: number | null;
  muted_until: string | null;
  notification_level: 'all' | 'mentions' | 'none';
  can_send: boolean;
  send_restriction: SendRestriction | null;
  created_at: string;
  last_message_at: string | null;
}

/** Contract `Message`. */
export interface Message {
  id: string;
  conversation_id: string;
  seq: number;
  client_message_id?: string | null;
  sender: UserSummary | null;
  kind: MessagePreview['kind'];
  body: string | null;
  /** DM-016: gift messages only; `opened_at` stays null until the recipient unwraps it. */
  gift?: MessageGift | null;
  attachments: MediaRef[];
  reply_to: MessagePreview | null;
  /** Group chats: the thread this message replies in, and how many replies it has itself. */
  thread_root_id?: string | null;
  thread_reply_count?: number;
  reactions: { emoji: string; count: number; reacted_by_me: boolean }[];
  pinned: boolean;
  moderation_state: 'visible' | 'removed_by_moderator' | 'removed_by_admin';
  edited_at: string | null;
  deleted_at: string | null;
  created_at: string;
}

/** Contract `MessageGift`. The code is a string so a gift added later still parses. */
export interface MessageGift {
  code: GiftCode | (string & {});
  opened_at: string | null;
}

export interface MessageList {
  data: Message[];
  page: { has_more: boolean; oldest_seq: number | null; newest_seq: number | null };
}

/**
 * Polling intervals for the REST fallback (ADR-0023): the staging API runs on serverless
 * functions without WebSockets, so open screens refresh on a timer and push covers the rest.
 */
export const POLL_INBOX_MS = 15_000;
export const POLL_CHAT_MS = 4_000;

export const messageKeys = {
  inbox: ['messages', 'inbox'] as const,
  conversation: (id: string) => ['messages', 'conversation', id] as const,
  history: (id: string) => ['messages', 'history', id] as const,
  pins: (id: string) => ['messages', 'pins', id] as const,
  thread: (id: string, rootId: string) => ['messages', 'thread', id, rootId] as const,
};

export function listConversations(client: ApiClient): Promise<Page<Conversation>> {
  return client.get<Page<Conversation>>('/v1/conversations', { query: { limit: 50 } });
}

export function openDirect(client: ApiClient, userId: string): Promise<Conversation> {
  return client.post<Conversation>('/v1/conversations', {
    body: { kind: 'direct', user_id: userId },
  });
}

export function getConversation(client: ApiClient, id: string): Promise<Conversation> {
  return client.get<Conversation>(`/v1/conversations/${id}`);
}

export function listMessages(client: ApiClient, id: string): Promise<MessageList> {
  return client.get<MessageList>(`/v1/conversations/${id}/messages`, { query: { limit: 50 } });
}

/** Idempotent on `clientMessageId` (DM-005): a retry returns the stored message. */
export function sendMessage(
  client: ApiClient,
  id: string,
  clientMessageId: string,
  body: string,
  replyToId?: string,
  attachmentIds: string[] = [],
): Promise<Message> {
  return client.post<Message>(`/v1/conversations/${id}/messages`, {
    idempotencyKey: clientMessageId,
    body: {
      client_message_id: clientMessageId,
      ...(body ? { body } : {}),
      ...(attachmentIds.length ? { kind: 'image', attachment_media_ids: attachmentIds } : {}),
      ...(replyToId ? { reply_to_message_id: replyToId } : {}),
    },
  });
}

/** DM-016: a gift (direct chats only); idempotent on `clientMessageId` like any send. */
export function sendGiftMessage(
  client: ApiClient,
  id: string,
  clientMessageId: string,
  gift: GiftCode,
  replyToId?: string,
): Promise<Message> {
  return client.post<Message>(`/v1/conversations/${id}/messages`, {
    idempotencyKey: clientMessageId,
    body: {
      client_message_id: clientMessageId,
      kind: 'gift',
      gift,
      ...(replyToId ? { reply_to_message_id: replyToId } : {}),
    },
  });
}

/** DM-016: the recipient unwraps a gift (idempotent); returns the message with `opened_at`. */
export function openGift(client: ApiClient, id: string, messageId: string): Promise<Message> {
  return client.post<Message>(`/v1/conversations/${id}/messages/${messageId}/gift/open`);
}

/** SCR-083: replies in a group chat thread, oldest first (GCHAT-004). */
export function listThread(client: ApiClient, id: string, rootId: string): Promise<MessageList> {
  return client.get<MessageList>(`/v1/conversations/${id}/threads/${rootId}`, {
    query: { limit: 200 },
  });
}

/** A reply in a thread; idempotent on `clientMessageId` like any send (DM-005). */
export function sendThreadReply(
  client: ApiClient,
  id: string,
  clientMessageId: string,
  rootId: string,
  body: string,
): Promise<Message> {
  return client.post<Message>(`/v1/conversations/${id}/messages`, {
    idempotencyKey: clientMessageId,
    body: { client_message_id: clientMessageId, body, thread_root_id: rootId },
  });
}

/** `PUT /v1/conversations/{id}/mute`: no push until `until` (null unmutes); in-app badges stay. */
export function muteConversation(
  client: ApiClient,
  id: string,
  until: Date | null,
): Promise<Conversation> {
  return client.put<Conversation>(`/v1/conversations/${id}/mute`, {
    body: { muted_until: until ? until.toISOString() : null },
  });
}

/** Quick reactions offered in the app (a subset of the server's allow-list). */
export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '🙏', '🎉'] as const;

/** `PUT`/`DELETE …/reactions/{emoji}` (idempotent; the emoji is percent-encoded). */
export function setMessageReaction(
  client: ApiClient,
  id: string,
  messageId: string,
  emoji: string,
  on: boolean,
): Promise<unknown> {
  const path = `/v1/conversations/${id}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`;
  return on ? client.put(path) : client.delete(path);
}

/** `POST /v1/conversations/{id}/clear`: hides messages up to `throughSeq` for me only. */
export async function clearConversation(
  client: ApiClient,
  id: string,
  throughSeq: number,
): Promise<void> {
  await client.post(`/v1/conversations/${id}/clear`, { body: { through_seq: throughSeq } });
}

/** SCR-084: pinned messages (at most 10, newest pin first). */
export function listPins(client: ApiClient, id: string): Promise<MessageList> {
  return client.get<MessageList>(`/v1/conversations/${id}/pins`);
}

export function pinMessage(client: ApiClient, id: string, messageId: string): Promise<unknown> {
  return client.put(`/v1/conversations/${id}/pins/${messageId}`);
}

export function unpinMessage(client: ApiClient, id: string, messageId: string): Promise<unknown> {
  return client.delete(`/v1/conversations/${id}/pins/${messageId}`);
}

export function markRead(client: ApiClient, id: string, seq: number): Promise<unknown> {
  return client.put(`/v1/conversations/${id}/receipts`, {
    body: { read_through_seq: seq, delivered_through_seq: seq },
  });
}

export function deleteMessage(
  client: ApiClient,
  conversationId: string,
  messageId: string,
): Promise<void> {
  return client.delete(`/v1/conversations/${conversationId}/messages/${messageId}`);
}

/** Tombstones, removed messages and messages of deleted accounts show no content. */
export function isHidden(
  message: Pick<Message, 'deleted_at' | 'moderation_state' | 'body' | 'attachments' | 'gift'>,
): boolean {
  return (
    message.deleted_at !== null ||
    message.moderation_state !== 'visible' ||
    (message.body === null && message.attachments.length === 0 && !message.gift)
  );
}
