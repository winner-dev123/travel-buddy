import { buildUrl, requestJson, type Query } from '../api/http';
import type { SessionTokens } from '../api/types';
import { KEYS, readItem, writeItem } from './storage';

interface StoredSession {
  refresh_token: string;
  refresh_token_expires_at: string;
}

const REFRESH_MARGIN_MS = 30_000;

/**
 * The platform tokens of one console tab, outside React state: the access token in memory, the
 * refresh token also in this tab's sessionStorage (ADR-0032). One refresh runs at a time.
 */
export class TokenStore {
  private access: { token: string; expiresAt: number } | null = null;
  private refreshToken: string | null = null;
  private refreshing: Promise<boolean> | null = null;
  private restoreClaimed = false;

  constructor(private readonly apiBaseUrl: string) {}

  url(path: string, query?: Query): string {
    return buildUrl(this.apiBaseUrl, path, query);
  }

  keep(tokens: SessionTokens): void {
    this.access = { token: tokens.access_token, expiresAt: Date.parse(tokens.access_token_expires_at) };
    this.refreshToken = tokens.refresh_token;
    const stored: StoredSession = {
      refresh_token: tokens.refresh_token,
      refresh_token_expires_at: tokens.refresh_token_expires_at,
    };
    writeItem('session', KEYS.session, JSON.stringify(stored));
  }

  forget(): void {
    this.access = null;
    this.refreshToken = null;
    writeItem('session', KEYS.session, null);
  }

  accessToken(): string | null {
    return this.access?.token ?? null;
  }

  expiresSoon(now = Date.now()): boolean {
    return this.access !== null && this.access.expiresAt - now < REFRESH_MARGIN_MS;
  }

  /** Loads a still-valid refresh token saved by this tab. False when there is none. */
  loadSaved(now = Date.now()): boolean {
    const raw = readItem('session', KEYS.session);
    let stored: Partial<StoredSession> | null;
    try {
      stored = raw ? (JSON.parse(raw) as Partial<StoredSession>) : null;
    } catch {
      stored = null;
    }
    if (!stored?.refresh_token || Date.parse(stored.refresh_token_expires_at ?? '') < now) {
      this.forget();
      return false;
    }
    this.refreshToken = stored.refresh_token;
    return true;
  }

  /** True the first time only: the saved session is restored once per tab load. */
  claimRestore(): boolean {
    if (this.restoreClaimed) return false;
    this.restoreClaimed = true;
    return true;
  }

  refresh(): Promise<boolean> {
    if (this.refreshing) return this.refreshing;
    const token = this.refreshToken;
    if (!token) return Promise.resolve(false);
    this.refreshing = (async () => {
      try {
        this.keep(
          await requestJson<SessionTokens>(this.url('/v1/auth/refresh'), {
            method: 'POST',
            body: { refresh_token: token },
          }),
        );
        return true;
      } catch {
        return false;
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }
}
