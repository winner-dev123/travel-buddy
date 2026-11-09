import * as SecureStore from 'expo-secure-store';

/**
 * Platform session tokens (docs/02 §8).
 *
 * - Access token (JWT, ~15 min): kept in memory only and lost when the app is
 *   killed. It is re-obtained with the refresh token at launch.
 * - Refresh token (opaque, rotated on every use): kept in the OS keychain or
 *   keystore via expo-secure-store. It is readable only on this device after
 *   first unlock, and is not included in backups or migrated to new devices.
 */

const REFRESH_TOKEN_KEY = 'travelbuddy.session.refresh_token';

const secureOptions: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY,
};

let accessToken: string | null = null;

export const tokenStore = {
  getAccessToken(): string | null {
    return accessToken;
  },

  setAccessToken(token: string | null): void {
    accessToken = token;
  },

  async getRefreshToken(): Promise<string | null> {
    return SecureStore.getItemAsync(REFRESH_TOKEN_KEY, secureOptions);
  },

  async setRefreshToken(token: string): Promise<void> {
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token, secureOptions);
  },

  /** Sign-out / session revocation: forget both tokens. */
  async clear(): Promise<void> {
    accessToken = null;
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY, secureOptions);
  },
};
