// req: DM-014, AUTH-007
import NetInfo from '@react-native-community/netinfo';

import { ApiClient } from '@/api';
import { enqueueMessage, useOutboxStore } from '@/features/messages/outbox';

import { readCachedMe } from '../deviceSession';
import { refreshAccessToken, restoreSession, signOut } from '../session';
import { useSessionStore } from '../sessionStore';
import { tokenStore } from '../tokenStore';
import type { Me } from '../types';

jest.mock('expo-crypto', () => ({ randomUUID: () => '0b8c2f4e-5d6a-4b7c-8e9f-0a1b2c3d4e5f' }));
jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const name = (part: unknown) => (typeof part === 'string' ? part : 'doc');
  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts.map(name).join('/');
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
    delete() {
      files.delete(this.uri);
    }
  }
  return { File, Paths: { document: {} }, mockFiles: files };
});

const fs = jest.requireMock<{ mockFiles: Map<string, string> }>('expo-file-system');

const ME = {
  account: {
    id: 'u1',
    email: 'ana@example.com',
    email_verified: true,
    status: 'active',
    primary_locale: 'en',
  },
  profile: {
    id: 'u1',
    handle: 'ana.souza',
    display_name: 'Ana Souza',
    bio: null,
    account_visibility: 'public',
  },
  preferences: { ui_locale: 'en', time_zone: 'UTC' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: true,
} as unknown as Me;
const TOKENS = {
  token_type: 'Bearer',
  access_token: 'access-1',
  access_token_expires_at: '2026-11-09T12:15:00Z',
  refresh_token: 'refresh-2',
  refresh_token_expires_at: '2026-12-09T12:00:00Z',
  session_id: 's1',
};

function json(status: number, body: unknown, contentType = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': contentType } });
}

/** An API client like the app's: a signed-in session without a token refreshes first. */
function client(handler: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; auth?: string }[] = [];
  const api: ApiClient = new ApiClient({
    baseUrl: 'https://api.test',
    getAccessToken: () => tokenStore.getAccessToken(),
    getLocale: () => 'en',
    generateId: () => '00000000-0000-4000-8000-000000000000',
    refreshAccessToken: () => refreshAccessToken(api),
    hasSession: () => useSessionStore.getState().status === 'signed_in',
    fetchImpl: async (input, init) => {
      const url = String(input);
      calls.push({ url, auth: (init?.headers as Record<string, string>)?.Authorization });
      return handler(url, init ?? {});
    },
  });
  return { api, calls };
}

const offline = () => {
  throw new TypeError('Network request failed');
};

/** The app starting again: nothing in memory, the refresh token in secure storage. */
async function relaunch() {
  tokenStore.setAccessToken(null);
  useSessionStore.setState({ status: 'restoring', me: null });
}

let networkListeners: ((state: { isConnected: boolean; isInternetReachable: boolean }) => void)[];

beforeEach(async () => {
  fs.mockFiles.clear();
  useOutboxStore.setState({ items: [] });
  await tokenStore.clear();
  useSessionStore.getState().setSignedOut();
  networkListeners = [];
  jest.mocked(NetInfo.addEventListener).mockImplementation((listener) => {
    networkListeners.push(listener as (typeof networkListeners)[number]);
    return () => {
      networkListeners = networkListeners.filter((l) => l !== listener);
    };
  });
});

it('stays signed in when the network fails at launch, and finishes once it is back', async () => {
  useSessionStore.getState().setSignedIn(ME); // signed in on an earlier run
  await tokenStore.setRefreshToken('refresh-1');
  await relaunch();

  let online = false;
  const { api, calls } = client((url) => {
    if (!online) offline();
    return url.endsWith('/v1/auth/refresh')
      ? json(200, TOKENS)
      : json(200, { ...ME, profile: { ...ME.profile, display_name: 'Ana S.' } });
  });
  await restoreSession(api);
  expect(useSessionStore.getState().status).toBe('signed_in');
  expect(useSessionStore.getState().me?.profile.display_name).toBe('Ana Souza');
  await expect(tokenStore.getRefreshToken()).resolves.toBe('refresh-1'); // kept

  online = true;
  calls.length = 0;
  networkListeners.forEach((listener) =>
    listener({ isConnected: true, isInternetReachable: true }),
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(calls.map((call) => call.url)).toEqual([
    'https://api.test/v1/auth/refresh',
    'https://api.test/v1/users/me',
  ]);
  expect(calls[1]?.auth).toBe('Bearer access-1');
  expect(useSessionStore.getState().me?.profile.display_name).toBe('Ana S.');
});

it('starts signed out after a network failure when this device has no saved profile', async () => {
  await tokenStore.setRefreshToken('refresh-1');
  await relaunch();
  const { api } = client(offline);
  await restoreSession(api);
  expect(useSessionStore.getState().status).toBe('signed_out');
  await expect(tokenStore.getRefreshToken()).resolves.toBe('refresh-1');
});

it('wipes queued messages and the saved profile when the session was revoked', async () => {
  useSessionStore.getState().setSignedIn(ME);
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null });
  await tokenStore.setRefreshToken('revoked');
  await relaunch();
  const { api } = client(() =>
    json(
      401,
      { type: 'x', title: 'Revoked', status: 401, code: 'session_revoked' },
      'application/problem+json',
    ),
  );
  await restoreSession(api);
  expect(useSessionStore.getState().status).toBe('signed_out');
  expect(readCachedMe()).toBeNull();
  expect(useOutboxStore.getState().items).toEqual([]);
});

it('wipes queued messages and the saved profile on sign-out', async () => {
  useSessionStore.getState().setSignedIn(ME);
  expect(readCachedMe()?.account.id).toBe('u1');
  enqueueMessage({ clientMessageId: 'cm-1', conversationId: 'c1', body: 'Hi', replyTo: null });
  const { api } = client(() => json(204, {}));
  await signOut(api);
  expect(readCachedMe()).toBeNull();
  expect(useOutboxStore.getState().items).toEqual([]);
  expect([...fs.mockFiles.keys()]).toEqual(['doc/chat-outbox.json']);
  expect(fs.mockFiles.get('doc/chat-outbox.json')).toBe('[]');
});
