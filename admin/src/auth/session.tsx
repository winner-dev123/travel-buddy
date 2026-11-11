import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { createAdminApi, type AdminApi } from '../api/admin';
import { ApiError, buildUrl, requestJson, type RequestOptions } from '../api/http';
import type { AuthResult, Me, Permission, SessionTokens } from '../api/types';
import type { ConsoleConfig } from '../config';
import { deviceId, KEYS, readItem, writeItem } from './storage';

export type SignedOutNotice = 'signed_out' | 'timed_out' | 'session_expired' | 'no_staff_access';

export type AuthState =
  | { status: 'restoring' }
  | { status: 'signed_out'; notice?: SignedOutNotice }
  | { status: 'signed_in'; me: Me };

interface StoredSession {
  refresh_token: string;
  refresh_token_expires_at: string;
}

export interface Session {
  state: AuthState;
  api: AdminApi;
  config: ConsoleConfig;
  /** Exchange a Firebase ID token (with the second factor) for a platform staff session. */
  signIn: (idToken: string) => Promise<'ok' | 'no_staff_access'>;
  /** Whether the account behind an ID token is staff, without keeping a session. */
  isStaff: (idToken: string) => Promise<boolean>;
  signOut: (notice?: SignedOutNotice) => Promise<void>;
  /** Why the staff member is working right now; sent as X-Audit-Justification (ADM-009). */
  reason: string | null;
  setReason: (reason: string | null) => void;
  can: (permission: Permission) => boolean;
}

const SessionContext = createContext<Session | null>(null);

const REFRESH_MARGIN_MS = 30_000;
const APP_VERSION = '0.1.0';

function loginBody(idToken: string) {
  return {
    id_token: idToken,
    client: 'web',
    device: { device_id: deviceId(), device_name: 'Staff console', app_version: APP_VERSION },
  };
}

export function SessionProvider({ config, children }: { config: ConsoleConfig; children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'restoring' });
  const [reason, setReasonState] = useState<string | null>(() => readItem('session', KEYS.reason));
  const access = useRef<{ token: string; expiresAt: number } | null>(null);
  const refreshToken = useRef<string | null>(null);
  const refreshing = useRef<Promise<boolean> | null>(null);

  const url = useCallback(
    (path: string, query?: RequestOptions['query']) => buildUrl(config.apiBaseUrl, path, query),
    [config.apiBaseUrl],
  );

  const keep = useCallback((tokens: SessionTokens) => {
    access.current = {
      token: tokens.access_token,
      expiresAt: Date.parse(tokens.access_token_expires_at),
    };
    refreshToken.current = tokens.refresh_token;
    const stored: StoredSession = {
      refresh_token: tokens.refresh_token,
      refresh_token_expires_at: tokens.refresh_token_expires_at,
    };
    writeItem('session', KEYS.session, JSON.stringify(stored));
  }, []);

  const forget = useCallback(() => {
    access.current = null;
    refreshToken.current = null;
    writeItem('session', KEYS.session, null);
  }, []);

  const refresh = useCallback(async (): Promise<boolean> => {
    if (refreshing.current) return refreshing.current;
    const token = refreshToken.current;
    if (!token) return false;
    refreshing.current = (async () => {
      try {
        const tokens = await requestJson<SessionTokens>(url('/v1/auth/refresh'), {
          method: 'POST',
          body: { refresh_token: token },
        });
        keep(tokens);
        return true;
      } catch {
        return false;
      } finally {
        refreshing.current = null;
      }
    })();
    return refreshing.current;
  }, [keep, url]);

  const signOut = useCallback(
    async (notice: SignedOutNotice = 'signed_out') => {
      const token = access.current?.token;
      forget();
      setState({ status: 'signed_out', notice });
      if (token) {
        await requestJson(url('/v1/auth/logout'), {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => undefined);
      }
    },
    [forget, url],
  );

  const request = useCallback(
    async <T,>(path: string, options: RequestOptions = {}): Promise<T> => {
      const send = async () => {
        const current = access.current;
        if (!current) throw new ApiError({ status: 401, code: 'unauthenticated' });
        const headers: Record<string, string> = {
          ...options.headers,
          Authorization: `Bearer ${current.token}`,
        };
        if (path.startsWith('/v1/admin/') && reason) {
          headers['X-Audit-Justification'] = reason;
        }
        return requestJson<T>(url(path, options.query), { ...options, headers });
      };
      if (access.current && access.current.expiresAt - Date.now() < REFRESH_MARGIN_MS) {
        if (!(await refresh())) {
          await signOut('session_expired');
          throw new ApiError({ status: 401, code: 'unauthenticated' });
        }
      }
      try {
        return await send();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        if (error.code === 'reauthentication_required') {
          await signOut('timed_out');
          throw error;
        }
        if (await refresh()) return send();
        await signOut('session_expired');
        throw error;
      }
    },
    [reason, refresh, signOut, url],
  );

  // createAdminApi only wraps `request` in named calls; nothing reads the token refs while
  // rendering, they are read when a query or mutation runs.
  // eslint-disable-next-line react-hooks/refs
  const api = useMemo(() => createAdminApi(request), [request]);

  const signIn = useCallback(
    async (idToken: string): Promise<'ok' | 'no_staff_access'> => {
      const result = await requestJson<AuthResult>(url('/v1/auth/login'), {
        method: 'POST',
        body: loginBody(idToken),
      });
      if (!result.user.permissions?.length) {
        await requestJson(url('/v1/auth/logout'), {
          method: 'POST',
          headers: { Authorization: `Bearer ${result.tokens.access_token}` },
        }).catch(() => undefined);
        return 'no_staff_access';
      }
      keep(result.tokens);
      setState({ status: 'signed_in', me: result.user });
      return 'ok';
    },
    [keep, url],
  );

  const isStaff = useCallback(
    async (idToken: string): Promise<boolean> => {
      const result = await requestJson<AuthResult>(url('/v1/auth/login'), {
        method: 'POST',
        body: loginBody(idToken),
      });
      await requestJson(url('/v1/auth/logout'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${result.tokens.access_token}` },
      }).catch(() => undefined);
      return Boolean(result.user.permissions?.length);
    },
    [url],
  );

  // Restore the tab's session after a reload (the refresh token lives in sessionStorage).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const raw = readItem('session', KEYS.session);
      const stored = raw ? (JSON.parse(raw) as Partial<StoredSession>) : null;
      if (!stored?.refresh_token || Date.parse(stored.refresh_token_expires_at ?? '') < Date.now()) {
        forget();
        if (!cancelled) setState({ status: 'signed_out' });
        return;
      }
      refreshToken.current = stored.refresh_token;
      if (!(await refresh())) {
        forget();
        if (!cancelled) setState({ status: 'signed_out', notice: 'session_expired' });
        return;
      }
      try {
        const me = await api.me();
        if (cancelled) return;
        setState(
          me.permissions?.length
            ? { status: 'signed_in', me }
            : { status: 'signed_out', notice: 'no_staff_access' },
        );
      } catch {
        forget();
        if (!cancelled) setState({ status: 'signed_out', notice: 'session_expired' });
      }
    })();
    return () => {
      cancelled = true;
    };
    // Runs once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setReason = useCallback((value: string | null) => {
    writeItem('session', KEYS.reason, value);
    setReasonState(value);
  }, []);

  const can = useCallback(
    (permission: Permission) =>
      state.status === 'signed_in' && Boolean(state.me.permissions?.includes(permission)),
    [state],
  );

  const value = useMemo<Session>(
    () => ({ state, api, config, signIn, isStaff, signOut, reason, setReason, can }),
    [state, api, config, signIn, isStaff, signOut, reason, setReason, can],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error('useSession outside SessionProvider');
  return session;
}

/** For tests: a fixed session value. */
export const SessionTestProvider = SessionContext.Provider;
