import type { QueryClient } from '@tanstack/react-query';
import { File, Paths } from 'expo-file-system';
import { create } from 'zustand';

import { ApiNetworkError, ApiProblem, getApiClient, type ApiClient } from '@/api';
import { onSessionEnded } from '@/auth/deviceSession';
import { useSessionStore } from '@/auth/sessionStore';
import type { UserSummary } from '@/features/feed/types';
import type { RealtimeClient, ServerFrame } from '@/features/realtime/client';
import { realtimeHandle } from '@/features/realtime/handle';

import { messageKeys, sendGiftMessage, sendMessage, type Message, type MessageList } from './api';
import { isGiftCode, type GiftCode } from './gifts';

/**
 * Messages waiting to reach the server (ADR-0033). A message shows in the chat as soon as it is
 * written, is kept in a file so it survives the app closing, and is sent over the realtime socket
 * (waiting for the ack) or, without one, over REST. Every retry reuses the message's
 * `client_message_id`, so a send that got through before the connection dropped is never
 * duplicated (DM-005). Network failures retry with backoff; a refusal stops with its reason.
 * Gifts (DM-016) go the same way: an item with `gift` and an empty body.
 */

export type FailureReason = 'filtered' | 'restricted' | 'rejected';

export interface OutboxItem {
  clientMessageId: string;
  conversationId: string;
  body: string;
  /** A gift instead of text (the body is empty). */
  gift?: GiftCode;
  replyTo: { id: string; snippet: string | null } | null;
  createdAt: string;
  status: 'sending' | 'failed';
  reason?: FailureReason;
  attempts: number;
  nextAttemptAt: number;
}

interface OutboxState {
  items: OutboxItem[];
  replace: (items: OutboxItem[]) => void;
}

export const useOutboxStore = create<OutboxState>()((set) => ({
  items: [],
  replace: (items) => set({ items }),
}));

const outboxFile = () => new File(Paths.document, 'chat-outbox.json');

function save(items: OutboxItem[]): void {
  useOutboxStore.getState().replace(items);
  try {
    outboxFile().writeSync(JSON.stringify(items));
  } catch {
    // Kept in memory until the app closes; nothing else to do.
  }
}

// Queued messages belong to the session: another account must never send them.
onSessionEnded(() => save([]));

/** Load messages left from the last run (call once at startup). */
export function hydrateOutbox(): void {
  try {
    const file = outboxFile();
    if (!file.exists) return;
    const items = JSON.parse(file.textSync()) as OutboxItem[];
    if (Array.isArray(items)) {
      // A send interrupted by the app closing is retried now.
      useOutboxStore
        .getState()
        .replace(
          items
            .map((item) => ({ ...item, nextAttemptAt: 0 }))
            .filter((i) => i.body || isGiftCode(i.gift)),
        );
    }
  } catch {
    // Unreadable file: start empty.
  }
}

export function enqueueMessage(
  item: Pick<OutboxItem, 'clientMessageId' | 'conversationId' | 'body' | 'replyTo' | 'gift'>,
  now: number = Date.now(),
): void {
  const items = useOutboxStore.getState().items;
  if (items.some((i) => i.clientMessageId === item.clientMessageId)) return;
  save([
    ...items,
    {
      ...item,
      createdAt: new Date(now).toISOString(),
      status: 'sending',
      attempts: 0,
      nextAttemptAt: 0,
    },
  ]);
}

export function retryMessage(clientMessageId: string): void {
  save(
    useOutboxStore
      .getState()
      .items.map((i) =>
        i.clientMessageId === clientMessageId
          ? { ...i, status: 'sending' as const, reason: undefined, nextAttemptAt: 0 }
          : i,
      ),
  );
}

export function discardMessage(clientMessageId: string): void {
  save(useOutboxStore.getState().items.filter((i) => i.clientMessageId !== clientMessageId));
}

/** The server has the message (echo or ack): drop it from the outbox. */
export function settleMessage(clientMessageId: string): void {
  if (useOutboxStore.getState().items.some((i) => i.clientMessageId === clientMessageId)) {
    discardMessage(clientMessageId);
  }
}

function update(clientMessageId: string, change: Partial<OutboxItem>): void {
  save(
    useOutboxStore
      .getState()
      .items.map((i) => (i.clientMessageId === clientMessageId ? { ...i, ...change } : i)),
  );
}

function backoffMs(attempts: number): number {
  return Math.min(60_000, 1000 * 2 ** Math.min(attempts, 6));
}

function reasonFor(code: string, fieldCodes: string[]): FailureReason {
  if (fieldCodes.includes('message_filtered') || code === 'message_filtered') return 'filtered';
  if (
    [
      'connection_required',
      'member_restricted',
      'chat_admins_only',
      'blocked',
      'forbidden',
      'not_found',
    ].includes(code)
  ) {
    return 'restricted';
  }
  return 'rejected';
}

export interface FlushDeps {
  client: ApiClient;
  queryClient: QueryClient;
  realtime: RealtimeClient | null;
  me: UserSummary | null;
  now?: () => number;
}

/** Put a persisted message into the cached history (cancelling a poll that would hide it). */
export async function showPersisted(queryClient: QueryClient, message: Message): Promise<void> {
  const key = messageKeys.history(message.conversation_id);
  await queryClient.cancelQueries({ queryKey: key });
  queryClient.setQueryData<MessageList>(key, (old) =>
    old && !old.data.some((m) => m.id === message.id)
      ? {
          data: [...old.data, message].sort((a, b) => a.seq - b.seq),
          page: { ...old.page, newest_seq: Math.max(old.page.newest_seq ?? 0, message.seq) },
        }
      : old,
  );
  void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
}

function fromAck(item: OutboxItem, frame: ServerFrame, me: UserSummary | null): Message {
  const data = frame.data ?? {};
  return {
    id: String(data.message_id),
    conversation_id: item.conversationId,
    seq: Number(data.seq),
    client_message_id: item.clientMessageId,
    sender: me,
    kind: item.gift ? 'gift' : 'text',
    body: item.gift ? null : item.body,
    gift: item.gift ? { code: item.gift, opened_at: null } : null,
    attachments: [],
    reply_to: item.replyTo
      ? {
          id: item.replyTo.id,
          seq: 0,
          sender_id: null,
          kind: 'text',
          snippet: item.replyTo.snippet,
          deleted: false,
          created_at: item.createdAt,
        }
      : null,
    reactions: [],
    pinned: false,
    moderation_state: 'visible',
    edited_at: null,
    deleted_at: null,
    created_at: String(data.created_at ?? item.createdAt),
  };
}

let flushing: Promise<void> | null = null;

/** Send every message that is due, oldest first. Safe to call often (one run at a time). */
export function flushOutbox(deps: FlushDeps): Promise<void> {
  flushing ??= runFlush(deps).finally(() => {
    flushing = null;
  });
  return flushing;
}

async function runFlush(deps: FlushDeps): Promise<void> {
  const now = deps.now ?? Date.now;
  const blocked = new Set<string>(); // keep each conversation in order
  for (const item of [...useOutboxStore.getState().items]) {
    if (item.status !== 'sending' || blocked.has(item.conversationId)) continue;
    if (item.nextAttemptAt > now()) {
      blocked.add(item.conversationId);
      continue;
    }
    const outcome = await sendOne(item, deps);
    if (outcome !== 'sent') blocked.add(item.conversationId);
  }
}

async function sendOne(item: OutboxItem, deps: FlushDeps): Promise<'sent' | 'later' | 'failed'> {
  const now = (deps.now ?? Date.now)();
  const later = (delay?: number) => {
    update(item.clientMessageId, {
      attempts: item.attempts + 1,
      nextAttemptAt: now + (delay ?? backoffMs(item.attempts)),
    });
    return 'later' as const;
  };
  if (deps.realtime?.isOnline) {
    try {
      const frame = await deps.realtime.request('message.send', {
        conversation_id: item.conversationId,
        client_message_id: item.clientMessageId,
        ...(item.gift ? { kind: 'gift', gift: item.gift } : { body: item.body }),
        ...(item.replyTo ? { reply_to_message_id: item.replyTo.id } : {}),
      });
      if (frame.type === 'message.ack') {
        discardMessage(item.clientMessageId);
        await showPersisted(deps.queryClient, fromAck(item, frame, deps.me));
        return 'sent';
      }
      if (frame.type === 'rate_limited') {
        return later(Number(frame.data?.retry_after_ms) || 5000);
      }
      if (frame.type === 'error' && frame.data?.retryable === false) {
        const code = String(frame.data?.code ?? '');
        const details =
          (frame.data?.details as { errors?: { code?: string }[] } | undefined)?.errors ?? [];
        update(item.clientMessageId, {
          status: 'failed',
          reason: reasonFor(
            code,
            details.map((e) => String(e.code ?? '')),
          ),
        });
        return 'failed';
      }
      return later();
    } catch {
      // No ack in time or the socket dropped: try REST right away (same client id).
    }
  }
  try {
    const message = item.gift
      ? await sendGiftMessage(
          deps.client,
          item.conversationId,
          item.clientMessageId,
          item.gift,
          item.replyTo?.id,
        )
      : await sendMessage(
          deps.client,
          item.conversationId,
          item.clientMessageId,
          item.body,
          item.replyTo?.id,
        );
    discardMessage(item.clientMessageId);
    await showPersisted(deps.queryClient, message);
    return 'sent';
  } catch (error) {
    if (error instanceof ApiProblem && error.status === 429) return later(5000);
    if (error instanceof ApiProblem && error.status < 500) {
      update(item.clientMessageId, {
        status: 'failed',
        reason: reasonFor(
          error.code,
          error.errors.map((field) => field.code),
        ),
      });
      return 'failed';
    }
    if (error instanceof ApiNetworkError || error instanceof ApiProblem) return later();
    return later();
  }
}

/** The signed-in traveller as a message sender (for messages shown before the server echoes). */
export function currentUserSummary(): UserSummary | null {
  const me = useSessionStore.getState().me;
  if (!me) return null;
  return {
    id: me.account.id,
    handle: me.profile.handle,
    display_name: me.profile.display_name,
    avatar: (me.profile.avatar as UserSummary['avatar']) ?? null,
  };
}

/** Send whatever is due now, over the app's realtime connection when it has one. */
export function sendQueuedMessages(queryClient: QueryClient): Promise<void> {
  return flushOutbox({
    client: getApiClient(),
    queryClient,
    realtime: realtimeHandle.current,
    me: currentUserSummary(),
  });
}
