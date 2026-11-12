// req: DM-005, DM-014, DM-016
import { QueryClient } from '@tanstack/react-query';

import { ApiNetworkError, ApiProblem, type ApiClient } from '@/api';
import type { RealtimeClient, ServerFrame } from '@/features/realtime/client';

import type { Message, MessageList } from '../api';
import {
  discardMessage,
  enqueueMessage,
  flushOutbox,
  hydrateOutbox,
  retryMessage,
  settleMessage,
  useOutboxStore,
} from '../outbox';

jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  class File {
    readonly uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts.map((part) => (typeof part === 'string' ? part : 'doc')).join('/');
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
  }
  return { File, Paths: { document: {} }, mockFiles: files };
});

const fs = jest.requireMock<{ mockFiles: Map<string, string> }>('expo-file-system');

const me = { id: 'u9', handle: 'me', display_name: 'Me', avatar: null };

function persisted(id: string, seq: number, clientMessageId: string, body: string): Message {
  return {
    id,
    conversation_id: 'c1',
    seq,
    client_message_id: clientMessageId,
    sender: me,
    kind: 'text',
    body,
    attachments: [],
    reply_to: null,
    reactions: [],
    pinned: false,
    moderation_state: 'visible',
    edited_at: null,
    deleted_at: null,
    created_at: '2026-11-11T10:00:00Z',
  };
}

function api(post: jest.Mock): ApiClient {
  return { post, newIdempotencyKey: () => 'k' } as unknown as ApiClient;
}

function socket(reply: (data: Record<string, unknown>) => ServerFrame | Promise<ServerFrame>) {
  const request = jest.fn(async (_type: string, data: Record<string, unknown>) => reply(data));
  return { realtime: { isOnline: true, request } as unknown as RealtimeClient, request };
}

let queryClient: QueryClient;
let clock = 1_000;
const now = () => clock;

beforeEach(() => {
  fs.mockFiles.clear();
  useOutboxStore.setState({ items: [] });
  clock = 1_000;
  queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  queryClient.setQueryData<MessageList>(['messages', 'history', 'c1'], {
    data: [],
    page: { has_more: false, oldest_seq: null, newest_seq: null },
  });
});
afterEach(() => queryClient.clear());

const history = () =>
  queryClient.getQueryData<MessageList>(['messages', 'history', 'c1'])?.data.map((m) => m.id);

it('keeps queued messages in a file so they survive the app closing', () => {
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null }, 5);
  useOutboxStore.setState({ items: [] }); // the app closes

  hydrateOutbox();
  expect(useOutboxStore.getState().items).toEqual([
    expect.objectContaining({ clientMessageId: 'cm-1', body: 'Hi', status: 'sending' }),
  ]);
});

it('does not queue the same message twice', () => {
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null });
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null });
  expect(useOutboxStore.getState().items).toHaveLength(1);
});

it('sends over the socket and shows the acknowledged message', async () => {
  const { realtime, request } = socket((data) => ({
    v: 1,
    type: 'message.ack',
    id: 'a',
    data: { message_id: 'm7', seq: 7, client_message_id: data.client_message_id },
  }));
  const post = jest.fn();
  enqueueMessage({
    clientMessageId: 'cm-1',
    conversationId: 'c1',
    body: 'Hi',
    replyTo: { id: 'm1', snippet: 'Dinner?' },
  });
  await flushOutbox({ client: api(post), queryClient, realtime, me, now });
  expect(request).toHaveBeenCalledWith('message.send', {
    conversation_id: 'c1',
    client_message_id: 'cm-1',
    body: 'Hi',
    reply_to_message_id: 'm1',
  });
  expect(post).not.toHaveBeenCalled();
  expect(history()).toEqual(['m7']);
  expect(useOutboxStore.getState().items).toEqual([]);
});

it('falls back to REST with the same client id when the socket gives no answer', async () => {
  const { realtime } = socket(() => Promise.reject(new Error('timeout')));
  const post = jest.fn(async () => persisted('m8', 8, 'cm-1', 'Hi'));
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null });
  await flushOutbox({ client: api(post), queryClient, realtime, me, now });
  expect(post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
    idempotencyKey: 'cm-1',
    body: { client_message_id: 'cm-1', body: 'Hi' },
  });
  expect(history()).toEqual(['m8']);
});

it('retries a network failure later with backoff, keeping the order within a chat', async () => {
  const post: jest.Mock = jest.fn(async () => {
    throw new ApiNetworkError('offline', 'r');
  });
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'one', replyTo: null });
  enqueueMessage({ clientMessageId: 'cm-2', conversationId: 'c1', body: 'two', replyTo: null });
  await flushOutbox({ client: api(post), queryClient, realtime: null, me, now });
  expect(post).toHaveBeenCalledTimes(1); // "two" waits behind "one"
  expect(useOutboxStore.getState().items[0]).toMatchObject({
    attempts: 1,
    nextAttemptAt: 2_000,
    status: 'sending',
  });

  await flushOutbox({ client: api(post), queryClient, realtime: null, me, now });
  expect(post).toHaveBeenCalledTimes(1); // not due yet

  clock = 2_000;
  post.mockImplementation(
    async (_path: string, { body }: { body: { client_message_id: string } }) =>
      persisted(
        body.client_message_id === 'cm-1' ? 'm1' : 'm2',
        body.client_message_id === 'cm-1' ? 1 : 2,
        body.client_message_id,
        'x',
      ),
  );
  await flushOutbox({ client: api(post), queryClient, realtime: null, me, now });
  expect(history()).toEqual(['m1', 'm2']);
  expect(useOutboxStore.getState().items).toEqual([]);
});

it('stops with a reason when the server refuses the message', async () => {
  const post = jest.fn(async () => {
    throw new ApiProblem(
      {
        type: 'x',
        title: 'Unprocessable',
        status: 422,
        code: 'validation_failed',
        errors: [{ field: '/body', code: 'message_filtered', message: 'No.' }],
      },
      'r',
    );
  });
  enqueueMessage({
    clientMessageId: 'cm-1',
    conversationId: 'c1',
    body: 'gift card?',
    replyTo: null,
  });
  await flushOutbox({ client: api(post), queryClient, realtime: null, me, now });
  expect(useOutboxStore.getState().items[0]).toMatchObject({
    status: 'failed',
    reason: 'filtered',
  });

  // Failed messages wait for the traveller: a flush doesn't resend them.
  await flushOutbox({ client: api(post), queryClient, realtime: null, me, now });
  expect(post).toHaveBeenCalledTimes(1);

  retryMessage('cm-1');
  expect(useOutboxStore.getState().items[0]).toMatchObject({
    status: 'sending',
    reason: undefined,
  });
  discardMessage('cm-1');
  expect(useOutboxStore.getState().items).toEqual([]);
});

it('marks a socket refusal as failed and a rate limit as retry-later', async () => {
  const { realtime } = socket((data) =>
    data.client_message_id === 'cm-1'
      ? { v: 1, type: 'error', id: 'e', data: { code: 'blocked', retryable: false } }
      : { v: 1, type: 'rate_limited', id: 'r', data: { retry_after_ms: 1500 } },
  );
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'a', replyTo: null });
  enqueueMessage({ clientMessageId: 'cm-2', conversationId: 'c2', body: 'b', replyTo: null });
  await flushOutbox({ client: api(jest.fn()), queryClient, realtime, me, now });
  const [first, second] = useOutboxStore.getState().items;
  expect(first).toMatchObject({ status: 'failed', reason: 'restricted' });
  expect(second).toMatchObject({ status: 'sending', nextAttemptAt: 2_500 });
});

it('drops a message from the outbox once the server echoes it', () => {
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null });
  settleMessage('cm-1');
  settleMessage('unknown');
  expect(useOutboxStore.getState().items).toEqual([]);
});

describe('gifts (DM-016)', () => {
  it('keeps a queued gift across restarts even though it has no text', () => {
    enqueueMessage({
      clientMessageId: 'cm-g',
      conversationId: 'c1',
      body: '',
      gift: 'flowers',
      giftEffect: 'hearts',
      replyTo: null,
    });
    useOutboxStore.setState({ items: [] }); // the app closes

    hydrateOutbox();
    expect(useOutboxStore.getState().items).toEqual([
      expect.objectContaining({
        clientMessageId: 'cm-g',
        gift: 'flowers',
        giftEffect: 'hearts',
        body: '',
      }),
    ]);
  });

  it('forgets an effect it does not know when the outbox is read back', () => {
    enqueueMessage({
      clientMessageId: 'cm-g',
      conversationId: 'c1',
      body: '',
      gift: 'flowers',
      giftEffect: 'fireworks' as never, // written by a newer app
      replyTo: null,
    });
    useOutboxStore.setState({ items: [] });

    hydrateOutbox();
    const [item] = useOutboxStore.getState().items;
    expect(item).toMatchObject({ clientMessageId: 'cm-g', gift: 'flowers' });
    expect(item!.giftEffect).toBeUndefined(); // sent as petals
  });

  it('sends a gift over the socket and shows it wrapped for nobody but me', async () => {
    const { realtime, request } = socket((data) => ({
      v: 1,
      type: 'message.ack',
      id: 'a',
      data: { message_id: 'm9', seq: 9, client_message_id: data.client_message_id },
    }));
    enqueueMessage({
      clientMessageId: 'cm-g',
      conversationId: 'c1',
      body: '',
      gift: 'coconut',
      giftEffect: 'splash',
      replyTo: null,
    });
    await flushOutbox({ client: api(jest.fn()), queryClient, realtime, me, now });
    expect(request).toHaveBeenCalledWith('message.send', {
      conversation_id: 'c1',
      client_message_id: 'cm-g',
      kind: 'gift',
      gift: 'coconut',
      gift_effect: 'splash',
    });
    const [shown] = queryClient.getQueryData<MessageList>(['messages', 'history', 'c1'])!.data;
    expect(shown).toMatchObject({
      id: 'm9',
      kind: 'gift',
      body: null,
      gift: { code: 'coconut', effect: 'splash', opened_at: null },
    });
  });

  it('falls back to REST for a gift with the same client id', async () => {
    const { realtime } = socket(() => Promise.reject(new Error('timeout')));
    const post = jest.fn(async () => ({
      ...persisted('m10', 10, 'cm-g', ''),
      kind: 'gift',
      body: null,
      gift: { code: 'cake', effect: 'petals', opened_at: null },
    }));
    enqueueMessage({
      clientMessageId: 'cm-g',
      conversationId: 'c1',
      body: '',
      gift: 'cake',
      replyTo: { id: 'm1', snippet: 'Happy birthday!' },
    });
    await flushOutbox({ client: api(post), queryClient, realtime, me, now });
    expect(post).toHaveBeenCalledWith('/v1/conversations/c1/messages', {
      idempotencyKey: 'cm-g',
      body: {
        client_message_id: 'cm-g',
        kind: 'gift',
        gift: 'cake',
        gift_effect: 'petals', // none chosen
        reply_to_message_id: 'm1',
      },
    });
    expect(history()).toEqual(['m10']);
    expect(useOutboxStore.getState().items).toEqual([]);
  });
});
