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

/** Who authenticates users (ADR-0020). `dev` is the backend's development IdP. */
export type IdentityProviderKind = 'supabase' | 'dev';

export interface SupabaseConfig {
  url: string;
  publishableKey: string;
}

export function getIdentityProviderKind(): IdentityProviderKind {
  const raw = process.env.EXPO_PUBLIC_IDENTITY_PROVIDER;
  if (raw === 'dev') {
    if (!__DEV__) {
      throw new ConfigurationError(
        'The development identity provider is not allowed in release builds.',
      );
    }
    return 'dev';
  }
  return 'supabase';
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
