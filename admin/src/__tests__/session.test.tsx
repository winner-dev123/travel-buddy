import { act, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SessionProvider, useSession, type Session } from '../auth/session';
import { KEYS } from '../auth/storage';
import { staffMe } from '../test/render';

const CONFIG = { apiBaseUrl: 'https://api.test', firebaseApiKey: 'k', environmentLabel: 'staging' };

function tokens(access: string, refresh = `refresh-${access}-${'x'.repeat(32)}`) {
  return {
    token_type: 'Bearer',
    access_token: access,
    access_token_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    refresh_token: refresh,
    refresh_token_expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    session_id: 'session-1',
  };
}

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

function json(status: number, body: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

function mount(handler: Handler) {
  const fetchMock = vi.fn(async (input: string | URL, init: RequestInit = {}) => handler(new URL(String(input)), init));
  vi.stubGlobal('fetch', fetchMock);
  let session: Session | null = null;
  function Probe() {
    session = useSession();
    return null;
  }
  render(
    <SessionProvider config={CONFIG}>
      <Probe />
    </SessionProvider>,
  );
  return { fetchMock, current: () => session! };
}

beforeEach(() => window.sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('staff session', () => {
  it('signs in staff and refuses accounts without a staff role', async () => {
    let staff = false;
    const { fetchMock, current } = mount((url) => {
      if (url.pathname === '/v1/auth/login') {
        const me = staffMe('moderator');
        return json(200, { tokens: tokens('a1'), user: staff ? me : { ...me, roles: [], permissions: [] }, is_new_user: false });
      }
      if (url.pathname === '/v1/auth/logout') return json(204, undefined);
      return json(404, { status: 404, code: 'not_found' });
    });
    await waitFor(() => expect(current().state.status).toBe('signed_out'));

    await act(async () => {
      expect(await current().signIn('id-token')).toBe('no_staff_access');
    });
    expect(current().state.status).toBe('signed_out');
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith('/v1/auth/logout'))).toBe(true);
    expect(window.sessionStorage.getItem(KEYS.session)).toBeNull();

    staff = true;
    await act(async () => {
      expect(await current().signIn('id-token')).toBe('ok');
    });
    expect(current().state.status).toBe('signed_in');
    expect(current().can('users.suspend')).toBe(true);
    expect(current().can('roles.assign')).toBe(false);
    const login = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/v1/auth/login'))!;
    expect(JSON.parse(String(login[1]!.body))).toMatchObject({ id_token: 'id-token', client: 'web' });
    expect(JSON.parse(window.sessionStorage.getItem(KEYS.session)!).refresh_token).toContain('refresh-a1');
  });

  it('sends the work reason as the audit justification, and only to admin routes', async () => {
    const seen: Record<string, Headers> = {};
    const { current } = mount((url, init) => {
      if (url.pathname === '/v1/auth/login') {
        return json(200, { tokens: tokens('a1'), user: staffMe('admin'), is_new_user: false });
      }
      seen[url.pathname] = new Headers(init.headers);
      return json(200, { data: [], page: { next_cursor: null, has_more: false } });
    });
    await waitFor(() => expect(current().state.status).toBe('signed_out'));
    await act(async () => {
      await current().signIn('id');
      current().setReason('Reviewing reports about spam rings');
    });
    await act(async () => {
      await current().api.users({ q: 'ana' });
      await current().api.me();
    });
    expect(seen['/v1/admin/users']!.get('Authorization')).toBe('Bearer a1');
    expect(seen['/v1/admin/users']!.get('X-Audit-Justification')).toBe('Reviewing reports about spam rings');
    expect(seen['/v1/users/me']!.get('X-Audit-Justification')).toBeNull();
    expect(window.sessionStorage.getItem(KEYS.reason)).toBe('Reviewing reports about spam rings');
  });

  it('refreshes an expired token once and retries', async () => {
    let calls = 0;
    const { current } = mount((url, init) => {
      if (url.pathname === '/v1/auth/login') {
        return json(200, { tokens: tokens('old'), user: staffMe('admin'), is_new_user: false });
      }
      if (url.pathname === '/v1/auth/refresh') return json(200, tokens('new'));
      calls += 1;
      const auth = new Headers(init.headers).get('Authorization');
      return auth === 'Bearer new'
        ? json(200, { generated_at: 'now' })
        : json(401, { status: 401, code: 'unauthenticated' });
    });
    await waitFor(() => expect(current().state.status).toBe('signed_out'));
    await act(async () => {
      await current().signIn('id');
    });
    await act(async () => {
      await expect(current().api.overview()).resolves.toEqual({ generated_at: 'now' });
    });
    expect(calls).toBe(2);
    expect(current().state.status).toBe('signed_in');
  });

  it('signs out with a notice when the staff session timed out', async () => {
    const { current } = mount((url) => {
      if (url.pathname === '/v1/auth/login') {
        return json(200, { tokens: tokens('a1'), user: staffMe('admin'), is_new_user: false });
      }
      if (url.pathname === '/v1/auth/logout') return json(204, undefined);
      return json(401, { status: 401, code: 'reauthentication_required' });
    });
    await waitFor(() => expect(current().state.status).toBe('signed_out'));
    await act(async () => {
      await current().signIn('id');
    });
    await act(async () => {
      await expect(current().api.overview()).rejects.toMatchObject({ code: 'reauthentication_required' });
    });
    expect(current().state).toEqual({ status: 'signed_out', notice: 'timed_out' });
    expect(window.sessionStorage.getItem(KEYS.session)).toBeNull();
  });

  it('restores the tab session after a reload', async () => {
    window.sessionStorage.setItem(
      KEYS.session,
      JSON.stringify({ refresh_token: 'r'.repeat(40), refresh_token_expires_at: new Date(Date.now() + 60_000).toISOString() }),
    );
    const { current } = mount((url) => {
      if (url.pathname === '/v1/auth/refresh') return json(200, tokens('restored'));
      if (url.pathname === '/v1/users/me') return json(200, staffMe('support'));
      return json(404, { status: 404, code: 'not_found' });
    });
    await waitFor(() => expect(current().state.status).toBe('signed_in'));
    expect(current().can('moderation.reports.read')).toBe(true);
  });
});
