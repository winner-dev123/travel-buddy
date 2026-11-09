import { randomUUID } from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import { ApiProblem, type ApiClient } from '@/api';

import { useSessionStore } from './sessionStore';
import { tokenStore } from './tokenStore';
import type { AuthResult, LegalDocuments, Me, SessionTokens } from './types';

/**
 * Platform session flows (ADR-0003/0020): an IdP token (Supabase or the dev IdP) is exchanged
 * ONCE for platform tokens; only those are kept (refresh token in secure storage).
 */

export const APP_VERSION = '0.1.0';
const DEVICE_ID_KEY = 'travelbuddy.device_id';

export type ExchangeOutcome = { kind: 'signed_in'; me: Me } | { kind: 'registration_required' };

export interface RegistrationInput {
  /** YYYY-MM-DD. Only the year is stored server-side. */
  birthDate: string;
  legal: LegalDocuments;
  locale: string;
}

function clientPlatform(): 'ios' | 'android' {
  return Platform.OS === 'ios' ? 'ios' : 'android';
}

const DEVICE_ID_OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
};
let cachedDeviceId: string | null = null;

/**
 * A random per-install identifier (not a hardware ID), used only to label sessions. Read and
 * written with the SAME options, and never fatal: some devices and emulators fail keystore
 * decryption, in which case a fresh ID is generated (it is a label, not a secret).
 */
export async function getDeviceId(): Promise<string> {
  if (cachedDeviceId) {
    return cachedDeviceId;
  }
  let existing: string | null = null;
  try {
    existing = await SecureStore.getItemAsync(DEVICE_ID_KEY, DEVICE_ID_OPTIONS);
  } catch {
    await SecureStore.deleteItemAsync(DEVICE_ID_KEY, DEVICE_ID_OPTIONS).catch(() => undefined);
  }
  if (!existing) {
    existing = randomUUID();
    await SecureStore.setItemAsync(DEVICE_ID_KEY, existing, DEVICE_ID_OPTIONS).catch(
      () => undefined,
    );
  }
  cachedDeviceId = existing;
  return existing;
}

async function device(): Promise<{ device_id: string; app_version: string }> {
  return { device_id: await getDeviceId(), app_version: APP_VERSION };
}

async function applyTokens(tokens: SessionTokens): Promise<void> {
  tokenStore.setAccessToken(tokens.access_token);
  await tokenStore.setRefreshToken(tokens.refresh_token);
}

async function signedIn(result: AuthResult): Promise<Me> {
  await applyTokens(result.tokens);
  useSessionStore.getState().setSignedIn(result.user);
  return result.user;
}

/** `POST /v1/auth/login`. An unknown identity means the user must register first. */
export async function exchangeIdToken(
  client: ApiClient,
  idToken: string,
): Promise<ExchangeOutcome> {
  try {
    const result = await client.post<AuthResult>('/v1/auth/login', {
      body: { id_token: idToken, client: clientPlatform(), device: await device() },
    });
    return { kind: 'signed_in', me: await signedIn(result) };
  } catch (error) {
    if (error instanceof ApiProblem && error.status === 404 && error.code === 'not_found') {
      useSessionStore.getState().setPendingIdToken(idToken);
      return { kind: 'registration_required' };
    }
    throw error;
  }
}

/** `POST /v1/auth/register` with the age gate and the current legal versions (AUTH-008/009). */
export async function register(client: ApiClient, input: RegistrationInput): Promise<Me> {
  const idToken = useSessionStore.getState().pendingIdToken;
  if (!idToken) {
    throw new Error('No pending sign-in to register. Sign in again.');
  }
  const result = await client.post<AuthResult>('/v1/auth/register', {
    idempotencyKey: client.newIdempotencyKey(),
    body: {
      id_token: idToken,
      client: clientPlatform(),
      birth_date: input.birthDate,
      accepted_terms_version: input.legal.terms_version,
      accepted_privacy_version: input.legal.privacy_version,
      locale: input.locale,
      device: await device(),
    },
  });
  return signedIn(result);
}

/** At launch: rotate the stored refresh token and load `Me`. Any failure means signed out. */
export async function restoreSession(client: ApiClient): Promise<void> {
  const store = useSessionStore.getState();
  let refreshToken: string | null;
  try {
    refreshToken = await tokenStore.getRefreshToken();
  } catch (error) {
    // Unreadable secure storage (seen on some emulators): start signed out, drop the entry.
    if (__DEV__) {
      console.warn('[session] refresh token unreadable', error);
    }
    await tokenStore.clear().catch(() => undefined);
    store.setSignedOut();
    return;
  }
  if (!refreshToken) {
    store.setSignedOut();
    return;
  }
  try {
    const tokens = await client.post<SessionTokens>('/v1/auth/refresh', {
      body: { refresh_token: refreshToken },
    });
    await applyTokens(tokens);
    store.setSignedIn(await client.get<Me>('/v1/users/me'));
  } catch (error) {
    if (__DEV__) {
      console.warn('[session] restore failed', error);
    }
    if (error instanceof ApiProblem) {
      await tokenStore.clear(); // revoked, expired or reused: the session is gone
    }
    // Network errors keep the refresh token for the next launch.
    store.setSignedOut();
  }
}

/**
 * Rotate the refresh token for a new access token (the API client calls this on
 * `401 token_expired`). A rejected refresh ends the session; a network error keeps it.
 */
export async function refreshAccessToken(client: ApiClient): Promise<boolean> {
  const refreshToken = await tokenStore.getRefreshToken().catch(() => null);
  if (!refreshToken) {
    return false;
  }
  try {
    const tokens = await client.post<SessionTokens>('/v1/auth/refresh', {
      body: { refresh_token: refreshToken },
    });
    await applyTokens(tokens);
    return true;
  } catch (error) {
    if (error instanceof ApiProblem) {
      await tokenStore.clear();
      useSessionStore.getState().setSignedOut();
    }
    return false;
  }
}

export async function signOut(client: ApiClient): Promise<void> {
  try {
    if (tokenStore.getAccessToken()) {
      await client.post('/v1/auth/logout', { body: {} });
    }
  } catch {
    // Signing out locally must always succeed; the server session expires anyway.
  } finally {
    await tokenStore.clear();
    useSessionStore.getState().setSignedOut();
  }
}

export async function fetchLegalDocuments(client: ApiClient): Promise<LegalDocuments> {
  const config = await client.get<{ legal: LegalDocuments }>('/v1/client-config', {
    query: { platform: clientPlatform(), app_version: APP_VERSION },
  });
  return config.legal;
}
