/**
 * Build-time configuration. Expo inlines `process.env.EXPO_PUBLIC_*` at bundle
 * time, so each variable must be referenced literally (no dynamic lookup).
 */

export class ConfigurationError extends Error {
  override name = 'ConfigurationError';
}

export function getApiBaseUrl(): string {
  const raw: string | undefined = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (!raw) {
    throw new ConfigurationError(
      'EXPO_PUBLIC_API_BASE_URL is not set. Copy mobile/.env.example to mobile/.env.local.',
    );
  }
  return normalizeBaseUrl(raw);
}

export function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//.test(trimmed)) {
    throw new ConfigurationError(`API base URL must start with http:// or https://: "${raw}"`);
  }
  return trimmed;
}

export function getFeatureFlagOverrides(): string[] {
  // Overrides are a development aid only; production builds ignore them.
  if (!__DEV__) {
    return [];
  }
  const raw: string = process.env.EXPO_PUBLIC_FEATURE_FLAGS ?? '';
  return raw
    .split(',')
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}

/**
 * Who authenticates users: Firebase Authentication (ADR-0028), Supabase Auth (ADR-0020, until the
 * move is complete) or, in development builds, the backend's development IdP.
 */
export type IdentityProviderKind = 'firebase' | 'supabase' | 'dev';

export interface SupabaseConfig {
  url: string;
  publishableKey: string;
}

export interface FirebaseConfig {
  /** The project's Web API key: identifies the project, not a secret (ADR-0028). */
  apiKey: string;
}

export function getIdentityProviderKind(): IdentityProviderKind {
  return resolveIdentityProvider(
    process.env.EXPO_PUBLIC_IDENTITY_PROVIDER,
    Boolean(process.env.EXPO_PUBLIC_FIREBASE_API_KEY),
    __DEV__,
  );
}

/** Explicit choice first; otherwise Firebase when its key is configured, else Supabase. */
export function resolveIdentityProvider(
  raw: string | undefined,
  hasFirebaseKey: boolean,
  isDev: boolean,
): IdentityProviderKind {
  if (raw === 'dev') {
    if (!isDev) {
      throw new ConfigurationError(
        'The development identity provider is not allowed in release builds.',
      );
    }
    return 'dev';
  }
  if (raw === 'firebase' || raw === 'supabase') {
    return raw;
  }
  return hasFirebaseKey ? 'firebase' : 'supabase';
}

export function getFirebaseConfig(): FirebaseConfig {
  const apiKey: string | undefined = process.env.EXPO_PUBLIC_FIREBASE_API_KEY;
  if (!apiKey) {
    throw new ConfigurationError(
      'EXPO_PUBLIC_FIREBASE_API_KEY must be set (see mobile/.env.example).',
    );
  }
  return { apiKey: assertFirebaseWebApiKey(apiKey) };
}

/**
 * Only the Web API key may ship in the app bundle. A service-account key (JSON with a private key)
 * grants admin access to the project and is refused outright.
 */
export function assertFirebaseWebApiKey(key: string): string {
  const trimmed = key.trim();
  if (/private_key|BEGIN [A-Z ]*PRIVATE KEY|service_account/.test(trimmed)) {
    throw new ConfigurationError(
      'A Firebase SERVICE ACCOUNT key was configured. Only the Web API key may be bundled.',
    );
  }
  if (!/^AIza[0-9A-Za-z_-]{35}$/.test(trimmed)) {
    throw new ConfigurationError('EXPO_PUBLIC_FIREBASE_API_KEY is not a Firebase Web API key.');
  }
  return trimmed;
}

export function getSupabaseConfig(): SupabaseConfig {
  const url: string | undefined = process.env.EXPO_PUBLIC_SUPABASE_URL;
  const publishableKey: string | undefined = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !publishableKey) {
    throw new ConfigurationError(
      'EXPO_PUBLIC_SUPABASE_URL and EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY must be set (see mobile/.env.example).',
    );
  }
  return { url: normalizeBaseUrl(url), publishableKey: assertPublishableKey(publishableKey) };
}

/**
 * The app bundle is public, so only the publishable key may ship in it (ADR-0020).
 * Secret keys (`sb_secret_…`) and legacy service-role JWTs are refused outright.
 */
export function assertPublishableKey(key: string): string {
  const trimmed = key.trim();
  if (trimmed.startsWith('sb_secret_') || jwtRole(trimmed) === 'service_role') {
    throw new ConfigurationError(
      'A Supabase SECRET key was configured. Only the publishable key may be bundled.',
    );
  }
  return trimmed;
}

function jwtRole(token: string): string | undefined {
  const parts = token.split('.');
  if (parts.length !== 3 || !parts[1]) {
    return undefined;
  }
  try {
    const json = globalThis.atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
    const payload: unknown = JSON.parse(json);
    if (typeof payload === 'object' && payload !== null && 'role' in payload) {
      const role = (payload as { role: unknown }).role;
      return typeof role === 'string' ? role : undefined;
    }
  } catch {
    return undefined;
  }
  return undefined;
}
