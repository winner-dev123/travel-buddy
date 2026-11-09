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
