/**
 * The app's connection to the realtime gateway (docs/06, ADR-0023, ADR-0033).
 *
 * One socket while signed in and in the foreground. It authenticates with the platform access
 * token, pings every heartbeat interval, re-authenticates when the server says the token is about
 * to expire, and reconnects with jittered exponential backoff (immediately when asked, for
 * example when the network comes back). Close codes follow docs/06 §9. Frames answering a request
 * (`reply_to`) resolve that request; everything else goes to `onFrame`.
 */

export const PROTOCOL = 'travelbuddy.v1';

export type RealtimeStatus = 'idle' | 'connecting' | 'online' | 'waiting';

export interface ServerFrame {
  v: number;
  type: string;
  id: string;
  ts?: string;
  reply_to?: string;
  data?: Record<string, unknown>;
}

/** The subset of the WebSocket API the client needs (React Native's WebSocket fits). */
export interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code?: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}

export interface RealtimeOptions {
  url: string;
  getToken: () => string | null;
  refreshToken: () => Promise<boolean>;
  client: 'ios' | 'android';
  appVersion: string;
  newId: () => string;
  makeSocket?: (url: string, protocols: string[]) => SocketLike;
  random?: () => number;
  onFrame?: (frame: ServerFrame) => void;
  onStatus?: (status: RealtimeStatus) => void;
}

const OPEN = 1;
const MAX_BACKOFF_MS = 30_000;
const HEALTHY_AFTER_MS = 60_000;
/** docs/06 §9: stop for good (sign-out, suspension, upgrade, replaced, bad origin). */
const FINAL_CLOSES = new Set([4003, 4004, 4005, 4009, 4010]);

interface Pending {
  resolve: (frame: ServerFrame) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class RealtimeOfflineError extends Error {
  constructor() {
    super('The realtime connection is not open.');
    this.name = 'RealtimeOfflineError';
  }
}

export class RealtimeClient {
  private socket: SocketLike | null = null;
  private status: RealtimeStatus = 'idle';
  private wanted = false;
  private stopped = false;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private healthyTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly pending = new Map<string, Pending>();

  constructor(private readonly options: RealtimeOptions) {}

  get currentStatus(): RealtimeStatus {
    return this.status;
  }

  get isOnline(): boolean {
    return this.status === 'online';
  }

  /** Keep a connection open (until `stop`). */
  start(): void {
    this.wanted = true;
    if (this.stopped || this.socket || this.retryTimer) return;
    void this.connect();
  }

  /** Close the connection and stay closed (backgrounded, signed out). */
  stop(): void {
    this.wanted = false;
    this.clearRetry();
    const socket = this.socket;
    this.socket = null;
    this.teardown();
    if (socket) {
      socket.onclose = null;
      socket.close(1000);
    }
    this.setStatus('idle');
  }

  /** Reconnect now instead of waiting out the backoff (network back, app foregrounded). */
  reconnectNow(): void {
    if (!this.wanted || this.stopped || this.socket) return;
    this.clearRetry();
    void this.connect();
  }

  /** Send a frame and wait for the frame that answers it (`reply_to`). */
  request(type: string, data: Record<string, unknown>, timeoutMs = 10_000): Promise<ServerFrame> {
    if (!this.isOnline || !this.socket) return Promise.reject(new RealtimeOfflineError());
    const id = this.options.newId();
    return new Promise<ServerFrame>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new RealtimeOfflineError());
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.write(id, type, data);
    });
  }

  /** Fire and forget (typing, receipts). False when there is no open connection. */
  send(type: string, data: Record<string, unknown>): boolean {
    if (!this.isOnline || !this.socket) return false;
    this.write(this.options.newId(), type, data);
    return true;
  }

  private write(id: string, type: string, data: Record<string, unknown>): void {
    this.socket?.send(JSON.stringify({ v: 1, type, id, ts: new Date().toISOString(), data }));
  }

  private setStatus(status: RealtimeStatus): void {
    if (this.status === status) return;
    this.status = status;
    this.options.onStatus?.(status);
  }

  private async connect(): Promise<void> {
    if (!this.wanted || this.stopped) return;
    let token = this.options.getToken();
    if (!token && (await this.options.refreshToken().catch(() => false))) {
      token = this.options.getToken();
    }
    if (!token) {
      this.setStatus('waiting');
      this.schedule(this.backoff());
      return;
    }
    const make =
      this.options.makeSocket ??
      ((url: string, protocols: string[]) =>
        new WebSocket(url, protocols) as unknown as SocketLike);
    let socket: SocketLike;
    try {
      socket = make(this.options.url, [PROTOCOL]);
    } catch {
      this.setStatus('waiting');
      this.schedule(this.backoff());
      return;
    }
    this.socket = socket;
    this.setStatus('connecting');
    socket.onopen = () => this.authenticate(token);
    socket.onmessage = (event) => this.receive(event.data);
    socket.onerror = () => undefined; // onclose follows and decides what to do
    socket.onclose = (event) => this.closed(socket, event.code ?? 1006);
  }

  private authenticate(token: string): void {
    this.write(this.options.newId(), 'auth', {
      access_token: token,
      client: this.options.client,
      app_version: this.options.appVersion,
    });
  }

  private receive(raw: unknown): void {
    let frame: ServerFrame;
    try {
      frame = JSON.parse(String(raw)) as ServerFrame;
    } catch {
      return;
    }
    if (frame.reply_to) {
      const waiting = this.pending.get(frame.reply_to);
      if (waiting) {
        clearTimeout(waiting.timer);
        this.pending.delete(frame.reply_to);
        waiting.resolve(frame);
        return;
      }
    }
    switch (frame.type) {
      case 'auth.ok': {
        this.setStatus('online');
        const seconds = Number(frame.data?.heartbeat_interval_s) || 25;
        this.stopHeartbeat();
        this.heartbeat = setInterval(() => this.send('ping', {}), seconds * 1000);
        this.healthyTimer = setTimeout(() => {
          this.attempt = 0;
        }, HEALTHY_AFTER_MS);
        break;
      }
      case 'auth.expiring':
        void this.options
          .refreshToken()
          .catch(() => false)
          .then(() => {
            const token = this.options.getToken();
            if (token && this.socket?.readyState === OPEN) this.authenticate(token);
          });
        return;
      case 'pong':
        return;
      default:
        break;
    }
    this.options.onFrame?.(frame);
  }

  private closed(socket: SocketLike, code: number): void {
    if (this.socket !== socket) return;
    this.socket = null;
    this.teardown();
    if (!this.wanted) {
      this.setStatus('idle');
      return;
    }
    if (FINAL_CLOSES.has(code)) {
      this.stopped = true;
      this.setStatus('idle');
      return;
    }
    this.setStatus('waiting');
    if (code === 4001) {
      // The token expired or was refused: refresh, then try again soon.
      void this.options
        .refreshToken()
        .catch(() => false)
        .then(() => this.schedule(this.random() * 1000));
      return;
    }
    if (code === 4008) {
      this.schedule(60_000 + this.random() * 5000);
      return;
    }
    if (code === 1001 || code === 4011) {
      this.schedule(this.random() * 5000);
      return;
    }
    this.schedule(this.backoff());
  }

  private teardown(): void {
    this.stopHeartbeat();
    if (this.healthyTimer) clearTimeout(this.healthyTimer);
    this.healthyTimer = null;
    for (const [id, waiting] of this.pending) {
      clearTimeout(waiting.timer);
      waiting.reject(new RealtimeOfflineError());
      this.pending.delete(id);
    }
  }

  private stopHeartbeat(): void {
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = null;
  }

  private backoff(): number {
    const delay = this.random() * Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt);
    this.attempt += 1;
    return delay;
  }

  private random(): number {
    return (this.options.random ?? Math.random)();
  }

  private schedule(delayMs: number): void {
    this.clearRetry();
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.connect();
    }, delayMs);
  }

  private clearRetry(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }
}

/** `https://api.example` → `wss://api.example/v1/realtime` (no credentials in the URL). */
export function realtimeUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl.replace(/^http/, 'ws').replace(/\/+$/, '')}/v1/realtime`;
}
