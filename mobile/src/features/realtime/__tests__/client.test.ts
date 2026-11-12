// req: DM-003, DM-006, DM-008 (docs/06 §3, §9; ADR-0033)
import { PROTOCOL, RealtimeClient, realtimeUrl, type SocketLike } from '../client';

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: { type: string; id: string; data: Record<string, unknown> }[] = [];
  closedWith: number | undefined;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code?: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {}

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close(code?: number) {
    this.closedWith = code;
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(frame: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify({ v: 1, id: 's1', ...frame }) });
  }
  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

function setup(overrides: { token?: string | null; refresh?: () => Promise<boolean> } = {}) {
  const sockets: FakeSocket[] = [];
  const statuses: string[] = [];
  const frames: string[] = [];
  let next = 0;
  let token = overrides.token === undefined ? 'access-1' : overrides.token;
  const refreshToken = jest.fn(
    overrides.refresh ??
      (async () => {
        token = 'access-2';
        return true;
      }),
  );
  const client = new RealtimeClient({
    url: 'wss://api.test/v1/realtime',
    getToken: () => token,
    refreshToken,
    client: 'android',
    appVersion: '1.2.3',
    newId: () => `id-${++next}`,
    random: () => 0.5,
    makeSocket: (url, protocols) => {
      const socket = new FakeSocket(url, protocols);
      sockets.push(socket);
      return socket;
    },
    onStatus: (status) => statuses.push(status),
    onFrame: (frame) => frames.push(frame.type),
  });
  const connect = async () => {
    client.start();
    await Promise.resolve();
    const socket = sockets.at(-1)!;
    socket.open();
    socket.receive({ type: 'auth.ok', data: { heartbeat_interval_s: 25 } });
    return socket;
  };
  return { client, sockets, statuses, frames, refreshToken, connect };
}

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it('builds the socket URL from the API base URL', () => {
  expect(realtimeUrl('https://api.test')).toBe('wss://api.test/v1/realtime');
  expect(realtimeUrl('http://localhost:8000/')).toBe('ws://localhost:8000/v1/realtime');
});

it('authenticates in the first frame, never in the URL, and goes online on auth.ok', async () => {
  const { client, sockets, statuses, connect } = setup();
  const socket = await connect();
  expect(sockets[0]!.url).toBe('wss://api.test/v1/realtime');
  expect(sockets[0]!.protocols).toEqual([PROTOCOL]);
  expect(socket.sent[0]).toMatchObject({
    type: 'auth',
    data: { access_token: 'access-1', client: 'android', app_version: '1.2.3' },
  });
  expect(statuses).toEqual(['connecting', 'online']);
  expect(client.isOnline).toBe(true);
});

it('pings on the heartbeat interval', async () => {
  const { connect } = setup();
  const socket = await connect();
  jest.advanceTimersByTime(25_000);
  expect(socket.sent.at(-1)).toMatchObject({ type: 'ping' });
});

it('resolves a request with the frame that answers it and passes others on', async () => {
  const { client, frames, connect } = setup();
  const socket = await connect();
  const reply = client.request('message.send', { body: 'Hi' });
  const sent = socket.sent.at(-1)!;
  expect(sent).toMatchObject({ type: 'message.send', data: { body: 'Hi' } });
  socket.receive({ type: 'message.new', data: {} });
  socket.receive({ type: 'message.ack', reply_to: sent.id, data: { seq: 4 } });
  await expect(reply).resolves.toMatchObject({ type: 'message.ack', data: { seq: 4 } });
  expect(frames).toEqual(['auth.ok', 'message.new']);
});

it('fails pending requests when the connection drops, then reconnects with backoff', async () => {
  const { client, sockets, statuses, connect } = setup();
  const socket = await connect();
  const reply = client.request('message.send', { body: 'Hi' });
  socket.drop(1006);
  await expect(reply).rejects.toThrow('not open');
  expect(statuses.at(-1)).toBe('waiting');
  expect(client.send('typing.start', {})).toBe(false);

  jest.advanceTimersByTime(500); // random 0.5 × 1 s
  await Promise.resolve();
  expect(sockets).toHaveLength(2);
});

it('reconnects at once when asked (network back) instead of waiting out the backoff', async () => {
  const { client, sockets, connect } = setup();
  const socket = await connect();
  socket.drop(1006);
  client.reconnectNow();
  await Promise.resolve();
  expect(sockets).toHaveLength(2);
});

it('refreshes the token and retries soon after a 4001 close', async () => {
  const { sockets, refreshToken, connect } = setup();
  const socket = await connect();
  socket.drop(4001);
  await Promise.resolve();
  await Promise.resolve();
  expect(refreshToken).toHaveBeenCalled();
  jest.advanceTimersByTime(500);
  await Promise.resolve();
  sockets[1]!.open();
  expect(sockets[1]!.sent[0]).toMatchObject({ type: 'auth', data: { access_token: 'access-2' } });
});

it('stops for good on a final close code (signed out elsewhere)', async () => {
  const { client, sockets, statuses, connect } = setup();
  const socket = await connect();
  socket.drop(4003);
  expect(statuses.at(-1)).toBe('idle');
  jest.advanceTimersByTime(120_000);
  client.reconnectNow();
  await Promise.resolve();
  expect(sockets).toHaveLength(1);
});

it('re-authenticates on the same socket when the token is about to expire', async () => {
  const { connect } = setup();
  const socket = await connect();
  socket.receive({ type: 'auth.expiring', data: {} });
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  expect(socket.sent.at(-1)).toMatchObject({ type: 'auth', data: { access_token: 'access-2' } });
});

it('closes and stays idle when stopped (app in the background)', async () => {
  const { client, statuses, connect } = setup();
  const socket = await connect();
  client.stop();
  expect(socket.closedWith).toBe(1000);
  expect(statuses.at(-1)).toBe('idle');
  expect(client.isOnline).toBe(false);
});

it('waits without a token instead of opening a socket', async () => {
  const { client, sockets, statuses } = setup({ token: null, refresh: async () => false });
  client.start();
  await Promise.resolve();
  await Promise.resolve();
  expect(sockets).toHaveLength(0);
  expect(statuses).toEqual(['waiting']);
});
