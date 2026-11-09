import { z } from 'zod';

/**
 * Typed server environment with the safety rules from docs/web/01 §6 and §7.1:
 *  - the mock adapter is allowed only in development/test;
 *  - the development identity provider is allowed only in development/test;
 *  - staging/production require a real platform URL, a real session secret and OIDC settings.
 * A violation throws at startup instead of silently degrading.
 */
const schema = z.object({
  APP_ENV: z.enum(['development', 'test', 'staging', 'production']).default('development'),
  TB_API_MODE: z.enum(['mock', 'live']).optional(),
  TB_IDENTITY_PROVIDER: z.enum(['dev', 'oidc']).optional(),
  API_BASE_URL: z.string().url().optional(),
  REALTIME_URL: z.string().url().optional(),
  SESSION_SECRET: z.string().optional(),
  NEXT_PUBLIC_SITE_URL: z.string().url().default('http://localhost:3000'),
  NEXT_PUBLIC_MAP_STYLE_URL: z.string().url().optional(),
  OIDC_ISSUER: z.string().url().optional(),
  OIDC_CLIENT_ID: z.string().optional(),
  OIDC_CLIENT_SECRET: z.string().optional(),
  OIDC_REDIRECT_URI: z.string().url().optional(),
  ADMIN_ALLOWED_HOSTS: z.string().optional(),
  /** Comma-separated (current,previous) HMAC secrets for the platform's cache-revalidation webhook. */
  WEB_REVALIDATE_SECRETS: z.string().optional(),
});

/** Clearly labelled, deterministic secret usable ONLY in development/test. */
const DEV_SESSION_SECRET = 'travelbuddy-development-only-session-secret-do-not-use';

export interface ServerEnv {
  appEnv: 'development' | 'test' | 'staging' | 'production';
  apiMode: 'mock' | 'live';
  identityProvider: 'dev' | 'oidc';
  apiBaseUrl: string | null;
  realtimeUrl: string | null;
  sessionSecret: string;
  siteUrl: string;
  mapStyleUrl: string | null;
  oidc: { issuer: string; clientId: string; clientSecret: string; redirectUri: string } | null;
  adminAllowedHosts: string[];
  revalidateSecrets: string[];
  isDevLike: boolean;
  secureCookies: boolean;
}

export function parseEnv(source: Record<string, string | undefined>): ServerEnv {
  const raw = schema.parse(source);
  const isDevLike = raw.APP_ENV === 'development' || raw.APP_ENV === 'test';
  const apiMode = raw.TB_API_MODE ?? (isDevLike ? 'mock' : 'live');
  const identityProvider = raw.TB_IDENTITY_PROVIDER ?? (isDevLike ? 'dev' : 'oidc');
  const problems: string[] = [];

  if (apiMode === 'mock' && !isDevLike) problems.push(`TB_API_MODE=mock is forbidden when APP_ENV=${raw.APP_ENV}.`);
  if (identityProvider === 'dev' && !isDevLike) problems.push(`TB_IDENTITY_PROVIDER=dev is forbidden when APP_ENV=${raw.APP_ENV}.`);
  if (apiMode === 'live' && !raw.API_BASE_URL) problems.push('API_BASE_URL is required when TB_API_MODE=live.');
  if (!isDevLike && (!raw.SESSION_SECRET || raw.SESSION_SECRET.length < 32)) {
    problems.push('SESSION_SECRET (at least 32 characters) is required outside development/test.');
  }
  if (raw.SESSION_SECRET && raw.SESSION_SECRET === DEV_SESSION_SECRET && !isDevLike) {
    problems.push('The development session secret must not be used outside development/test.');
  }
  if (identityProvider === 'oidc' && !(raw.OIDC_ISSUER && raw.OIDC_CLIENT_ID && raw.OIDC_CLIENT_SECRET && raw.OIDC_REDIRECT_URI)) {
    problems.push('OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI are required for TB_IDENTITY_PROVIDER=oidc.');
  }
  if (!isDevLike && !raw.NEXT_PUBLIC_MAP_STYLE_URL) problems.push('NEXT_PUBLIC_MAP_STYLE_URL is required outside development/test (ADR-0014).');
  const revalidateSecrets = (raw.WEB_REVALIDATE_SECRETS ?? '').split(',').map((v) => v.trim()).filter(Boolean);
  if (revalidateSecrets.length > 2) problems.push('WEB_REVALIDATE_SECRETS accepts at most two secrets (current,previous).');
  if (revalidateSecrets.some((v) => v.length < 32)) problems.push('Each WEB_REVALIDATE_SECRETS value must be at least 32 characters.');
  if (problems.length > 0) throw new Error(`Invalid web environment:\n - ${problems.join('\n - ')}`);

  return {
    appEnv: raw.APP_ENV,
    apiMode,
    identityProvider,
    apiBaseUrl: raw.API_BASE_URL ?? null,
    realtimeUrl: raw.REALTIME_URL ?? null,
    sessionSecret: raw.SESSION_SECRET && raw.SESSION_SECRET.length >= 32 ? raw.SESSION_SECRET : DEV_SESSION_SECRET,
    siteUrl: raw.NEXT_PUBLIC_SITE_URL.replace(/\/+$/, ''),
    mapStyleUrl: raw.NEXT_PUBLIC_MAP_STYLE_URL ?? null,
    oidc:
      raw.OIDC_ISSUER && raw.OIDC_CLIENT_ID && raw.OIDC_CLIENT_SECRET && raw.OIDC_REDIRECT_URI
        ? { issuer: raw.OIDC_ISSUER, clientId: raw.OIDC_CLIENT_ID, clientSecret: raw.OIDC_CLIENT_SECRET, redirectUri: raw.OIDC_REDIRECT_URI }
        : null,
    revalidateSecrets,
    adminAllowedHosts: (raw.ADMIN_ALLOWED_HOSTS ?? '').split(',').map((h) => h.trim().toLowerCase()).filter(Boolean),
    isDevLike,
    secureCookies: !isDevLike || raw.NEXT_PUBLIC_SITE_URL.startsWith('https://'),
  };
}

let cached: ServerEnv | undefined;

export function env(): ServerEnv {
  return (cached ??= parseEnv(process.env));
}
