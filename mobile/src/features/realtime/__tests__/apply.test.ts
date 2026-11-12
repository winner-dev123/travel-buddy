// req: DM-006, DM-007, DM-008, NOTIF-006 (docs/06 §4–6; ADR-0033)
import { QueryClient } from '@tanstack/react-query';

import type { Conversation, Message, MessageList } from '@/features/messages/api';

import { applyFrame, syncRequest, type LiveNotification } from '../apply';
import type { RealtimeClient } from '../client';
import { realtimeHandle, reportTyping } from '../handle';
import { typingUsers, useRealtimeStore } from '../store';

const bo = { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null };
const me = { id: 'u9', handle: 'me', display_name: 'Me', avatar: null };

function message(id: string, seq: number, sender = bo, extra: Partial<Message> = {}): Message {
  return {
    id,
    conversation_id: 'c1',
    seq,
    sender,
    kind: 'text',
    body: `body ${id}`,
    attachments: [],
    reply_to: null,
    reactions: [],
    pinned: false,
    moderation_state: 'visible',
    edited_at: null,
    deleted_at: null,
    created_at: '2026-11-11T10:00:00Z',
    ...extra,
  };
}

function cached(client: QueryClient, messages: Message[]) {
  client.setQueryData<MessageList>(['messages', 'history', 'c1'], {
    data: messages,
    page: {
      has_more: false,
      oldest_seq: messages[0]?.seq ?? null,
      newest_seq: messages.at(-1)?.seq ?? null,
    },
  });
}

const history = (client: QueryClient) =>
  client.getQueryData<MessageList>(['messages', 'history', 'c1']);

function frame(type: string, data: Record<string, unknown>) {
  return { v: 1, type, id: 'f1', data };
}

let client: QueryClient;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  useRealtimeStore.setState({ status: 'idle', typing: {} });
});
afterEach(() => client.clear());

describe('message frames', () => {
  it('adds a new message to an open chat and clears its sender from typing', () => {
    cached(client, [message('m1', 1)]);
    useRealtimeStore.getState().setTyping('c1', 'u2', Date.now() + 8000);
    applyFrame(frame('message.new', { message: message('m2', 2) }), {
      queryClient: client,
      me: 'u9',
    });
    expect(history(client)?.data.map((m) => m.id)).toEqual(['m1', 'm2']);
    expect(history(client)?.page.newest_seq).toBe(2);
    expect(useRealtimeStore.getState().typing.c1).toEqual({});
  });

  it('settles my own message from another device or the echo of a send', () => {
    cached(client, [message('m1', 1)]);
    const onOwnMessage = jest.fn();
    applyFrame(
      frame('message.new', { message: message('m2', 2, me, { client_message_id: 'cm-1' }) }),
      { queryClient: client, me: 'u9', onOwnMessage },
    );
    expect(onOwnMessage).toHaveBeenCalledWith('cm-1', expect.objectContaining({ id: 'm2' }));
  });

  it('refetches instead of guessing when frames were missed (a seq gap)', () => {
    cached(client, [message('m1', 1)]);
    const invalidate = jest.spyOn(client, 'invalidateQueries');
    applyFrame(frame('message.new', { message: message('m5', 5) }), {
      queryClient: client,
      me: 'u9',
    });
    expect(history(client)?.data.map((m) => m.id)).toEqual(['m1']);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages', 'history', 'c1'] });
  });

  it('replaces an edited message and tombstones a deleted one', () => {
    cached(client, [message('m1', 1), message('m2', 2)]);
    applyFrame(
      frame('message.updated', {
        message: message('m1', 1, bo, { body: 'edited', edited_at: 'x' }),
      }),
      { queryClient: client, me: 'u9' },
    );
    applyFrame(
      frame('message.deleted', {
        conversation_id: 'c1',
        message_id: 'm2',
        deleted_at: '2026-11-11T10:05:00Z',
      }),
      { queryClient: client, me: 'u9' },
    );
    const [first, second] = history(client)!.data;
    expect(first!.body).toBe('edited');
    expect(second!.deleted_at).toBe('2026-11-11T10:05:00Z');
  });

  it('ignores messages for chats that are not cached (they load fresh when opened)', () => {
    applyFrame(frame('message.new', { message: message('m2', 2) }), {
      queryClient: client,
      me: 'u9',
    });
    expect(history(client)).toBeUndefined();
  });
});

describe('receipts and typing', () => {
  it("moves the other side's read and delivered marks forward, never back", () => {
    client.setQueryData<Partial<Conversation>>(['messages', 'conversation', 'c1'], {
      id: 'c1',
      peer_read_through_seq: 3,
      peer_delivered_through_seq: 3,
    });
    const apply = (data: Record<string, unknown>) =>
      applyFrame(frame('receipt.updated', { conversation_id: 'c1', user_id: 'u2', ...data }), {
        queryClient: client,
        me: 'u9',
      });
    apply({ read_through_seq: 5, delivered_through_seq: 6 });
    apply({ read_through_seq: 2 });
    expect(client.getQueryData(['messages', 'conversation', 'c1'])).toMatchObject({
      peer_read_through_seq: 5,
      peer_delivered_through_seq: 6,
    });
  });

  it('tracks who is typing until they stop or the indicator expires', () => {
    const now = 1_000_000;
    applyFrame(
      frame('typing', {
        conversation_id: 'c1',
        user_id: 'u2',
        state: 'started',
        expires_at: new Date(now + 8000).toISOString(),
      }),
      { queryClient: client, me: 'u9', now: () => now },
    );
    const typing = () => useRealtimeStore.getState().typing;
    expect(typingUsers(typing(), 'c1', 'u9', now)).toEqual(['u2']);
    expect(typingUsers(typing(), 'c1', 'u9', now + 9000)).toEqual([]);

    applyFrame(frame('typing', { conversation_id: 'c1', user_id: 'u2', state: 'stopped' }), {
      queryClient: client,
      me: 'u9',
    });
    expect(typingUsers(typing(), 'c1', 'u9', now)).toEqual([]);
  });

  it('forgets expired typing entries', () => {
    useRealtimeStore.getState().setTyping('c1', 'u2', 100);
    useRealtimeStore.getState().setTyping('c1', 'u3', 10_000);
    useRealtimeStore.getState().prune(5_000);
    expect(useRealtimeStore.getState().typing.c1).toEqual({ u3: 10_000 });
  });
});

describe('notifications and sync', () => {
  it('passes a friend request on for the banner and refreshes the request lists', () => {
    const onNotification = jest.fn();
    const invalidate = jest.spyOn(client, 'invalidateQueries');
    const notification: LiveNotification = {
      id: 'n1',
      type: 'connection_request',
      actor: { id: 'u2', handle: 'bo', display_name: 'Bo' },
      entity_type: 'connection_request',
      entity_id: 'r1',
      title: 'New connection request',
      body: 'Bo wants to connect',
      data: {},
      created_at: '2026-11-11T10:00:00Z',
    };
    applyFrame(frame('notification.new', { notification }), {
      queryClient: client,
      me: 'u9',
      onNotification,
    });
    expect(onNotification).toHaveBeenCalledWith(notification);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['me', 'notifications'] });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ['me', 'connection-requests', 'incoming'],
    });
  });

  it('asks for what was missed per cached chat and refetches what the server says changed', () => {
    cached(client, [message('m1', 1), message('m2', 2)]);
    expect(syncRequest(client)).toEqual([{ conversation_id: 'c1', last_seq: 2 }]);
    const invalidate = jest.spyOn(client, 'invalidateQueries');
    applyFrame(frame('sync.required', { conversations: [{ conversation_id: 'c1' }] }), {
      queryClient: client,
      me: 'u9',
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages', 'history', 'c1'] });
  });
});

describe('reportTyping', () => {
  function socket() {
    const send = jest.fn(() => true);
    realtimeHandle.current = { isOnline: true, send } as unknown as RealtimeClient;
    return send;
  }
  afterEach(() => {
    realtimeHandle.current = null;
  });

  it('sends typing.start at most every 3 s and typing.stop once', () => {
    const send = socket();
    reportTyping('c9', true, 0);
    reportTyping('c9', true, 1000);
    reportTyping('c9', true, 3500);
    reportTyping('c9', false, 4000);
    reportTyping('c9', false, 4100);
    expect(send.mock.calls).toEqual([
      ['typing.start', { conversation_id: 'c9' }],
      ['typing.start', { conversation_id: 'c9' }],
      ['typing.stop', { conversation_id: 'c9' }],
    ]);
  });

  it('stays silent without a connection (typing is never queued)', () => {
    reportTyping('c8', true, 0);
    const send = socket();
    reportTyping('c8', false, 10);
    expect(send).not.toHaveBeenCalled();
  });
});
