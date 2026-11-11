import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { createAdminApi, type AdminApi } from '../api/admin';
import { ApiError, requestJson, type RequestOptions } from '../api/http';
import type { AuthResult, Me, Permission } from '../api/types';
import type { ConsoleConfig } from '../config';
import { deviceId, KEYS, readItem, writeItem } from './storage';
import { TokenStore } from './tokens';

export type SignedOutNotice = 'signed_out' | 'timed_out' | 'session_expired' | 'no_staff_access';

export type AuthState =
  | { status: 'restoring' }
  | { status: 'signed_out'; notice?: SignedOutNotice }
  | { status: 'signed_in'; me: Me };

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
  const [tokens] = useState(() => new TokenStore(config.apiBaseUrl));

  const logout = useCallback(
    (accessToken: string) =>
      requestJson(tokens.url('/v1/auth/logout'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${accessToken}` },
      }).catch(() => undefined),
    [tokens],
  );

  const signOut = useCallback(
    async (notice: SignedOutNotice = 'signed_out') => {
      const token = tokens.accessToken();
      tokens.forget();
      setState({ status: 'signed_out', notice });
      if (token) await logout(token);
    },
    [logout, tokens],
  );

  const request = useCallback(
    async <T,>(path: string, options: RequestOptions = {}): Promise<T> => {
      const send = async () => {
        const token = tokens.accessToken();
        if (!token) throw new ApiError({ status: 401, code: 'unauthenticated' });
        const headers: Record<string, string> = { ...options.headers, Authorization: `Bearer ${token}` };
        if (path.startsWith('/v1/admin/') && reason) {
          headers['X-Audit-Justification'] = reason;
        }
        return requestJson<T>(tokens.url(path, options.query), { ...options, headers });
      };
      if (tokens.expiresSoon() && !(await tokens.refresh())) {
        await signOut('session_expired');
        throw new ApiError({ status: 401, code: 'unauthenticated' });
      }
      try {
        return await send();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        if (error.code === 'reauthentication_required') {
          await signOut('timed_out');
          throw error;
        }
        if (await tokens.refresh()) return send();
        await signOut('session_expired');
        throw error;
      }
    },
    [reason, signOut, tokens],
  );

  const api = useMemo(() => createAdminApi(request), [request]);

  const login = useCallback(
    (idToken: string) =>
      requestJson<AuthResult>(tokens.url('/v1/auth/login'), { method: 'POST', body: loginBody(idToken) }),
    [tokens],
  );

  const signIn = useCallback(
    async (idToken: string): Promise<'ok' | 'no_staff_access'> => {
      const result = await login(idToken);
      if (!result.user.permissions?.length) {
        await logout(result.tokens.access_token);
        return 'no_staff_access';
      }
      tokens.keep(result.tokens);
      setState({ status: 'signed_in', me: result.user });
      return 'ok';
    },
    [login, logout, tokens],
  );

  const isStaff = useCallback(
    async (idToken: string): Promise<boolean> => {
      const result = await login(idToken);
      await logout(result.tokens.access_token);
      return Boolean(result.user.permissions?.length);
    },
    [login, logout],
  );

  // Restore the tab's session after a reload (the refresh token lives in sessionStorage). The
  // store runs this once per tab load, even when React mounts the provider twice.
  useEffect(() => {
    if (!tokens.claimRestore()) return;
    void (async () => {
      if (!tokens.loadSaved()) {
        setState({ status: 'signed_out' });
        return;
      }
      if (!(await tokens.refresh())) {
        tokens.forget();
        setState({ status: 'signed_out', notice: 'session_expired' });
        return;
      }
      try {
        const me = await requestJson<Me>(tokens.url('/v1/users/me'), {
          headers: { Authorization: `Bearer ${tokens.accessToken()}` },
        });
        setState(
          me.permissions?.length
            ? { status: 'signed_in', me }
            : { status: 'signed_out', notice: 'no_staff_access' },
        );
      } catch {
        tokens.forget();
        setState({ status: 'signed_out', notice: 'session_expired' });
      }
    })();
  }, [tokens]);

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
