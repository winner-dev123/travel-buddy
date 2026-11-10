import type { ApiClient } from '@/api';
import type { MediaRef, Page, UserSummary } from '@/features/feed/types';

/** Contract `MessagePreview`. */
export interface MessagePreview {
  id: string;
  seq: number;
  sender_id: string | null;
  kind: 'text' | 'image' | 'system' | 'announcement';
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
  attachments: MediaRef[];
  reply_to: MessagePreview | null;
  reactions: { emoji: string; count: number; reacted_by_me: boolean }[];
  pinned: boolean;
  moderation_state: 'visible' | 'removed_by_moderator' | 'removed_by_admin';
  edited_at: string | null;
  deleted_at: string | null;
  created_at: string;
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
): Promise<Message> {
  return client.post<Message>(`/v1/conversations/${id}/messages`, {
    idempotencyKey: clientMessageId,
    body: {
      client_message_id: clientMessageId,
      body,
      ...(replyToId ? { reply_to_message_id: replyToId } : {}),
    },
  });
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
  message: Pick<Message, 'deleted_at' | 'moderation_state' | 'body' | 'attachments'>,
): boolean {
  return (
    message.deleted_at !== null ||
    message.moderation_state !== 'visible' ||
    (message.body === null && message.attachments.length === 0)
  );
}
