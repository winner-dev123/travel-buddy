import 'server-only';
import { localizedPath } from '@/lib/paths';
import { env } from './env';
import { codeChallengeS256, FLOW_TTL_SECONDS, newCodeVerifier, sealIdp } from './idp-flow';
import { createSupabaseAuth, type OAuthProvider } from './supabase-auth';

export type LoginIntent = 'login' | 'signup' | 'reset';
export type SocialProvider = 'google' | 'apple' | 'email';

export interface LoginStart {
  intent: LoginIntent;
  provider?: SocialProvider;
  next: string;
  locale: string;
}

export interface AuthorizationStart {
  /** Where the browser goes next (absolute IdP URL or a same-origin path). */
  url: string;
  /** Sealed `tb_idp_flow` cookie value to set alongside the redirect (PKCE verifier). */
  flowCookie?: string;
}

/**
 * Identity provider port (docs/web/01 §6). Credentials, verification and password reset are owned
 * by the IdP; the web only starts flows and completes the platform session.
 */
export interface IdentityProvider {
  readonly kind: 'dev' | 'oidc' | 'supabase';
  start(start: LoginStart): Promise<AuthorizationStart>;
}

/** Development/test only: a persona picker backed by the platform's dev IdP. */
class DevIdentityProvider implements IdentityProvider {
  readonly kind = 'dev' as const;
  async start(start: LoginStart): Promise<AuthorizationStart> {
    const params = new URLSearchParams({ intent: start.intent, next: start.next });
    if (start.provider) params.set('provider', start.provider);
    return { url: `${localizedPath(start.locale, '/dev/login')}?${params.toString()}` };
  }
}

/** Generic OIDC Authorization Code + PKCE. Not implemented: Supabase Auth is the IdP (ADR-0020). */
class OidcIdentityProvider implements IdentityProvider {
  readonly kind = 'oidc' as const;
  async start(): Promise<AuthorizationStart> {
    throw new Error('The generic OIDC identity provider is not implemented; use TB_IDENTITY_PROVIDER=supabase (ADR-0020).');
  }
}

/**
 * Supabase Auth (ADR-0020). Google/Apple go through `/auth/v1/authorize` with PKCE; the verifier
 * stays in a sealed HttpOnly cookie and the callback exchanges the code server-side. Email and
 * password flows use the web's own forms (login, register, forgot-password pages).
 */
class SupabaseIdentityProvider implements IdentityProvider {
  readonly kind = 'supabase' as const;
  constructor(private readonly config: { url: string; publishableKey: string; redirectUri: string }) {}

  async start(start: LoginStart): Promise<AuthorizationStart> {
    const query = new URLSearchParams({ next: start.next }).toString();
    if (start.intent === 'reset') return { url: `${localizedPath(start.locale, '/forgot-password')}?${query}` };
    if (start.provider !== 'google' && start.provider !== 'apple') {
      return { url: `${localizedPath(start.locale, start.intent === 'signup' ? '/register' : '/login')}?${query}` };
    }
    const provider: OAuthProvider = start.provider;
    const auth = createSupabaseAuth(this.config);
    const settings = await auth.settings();
    if (!settings.providers[provider]) throw new Error(`Supabase Auth provider "${provider}" is not enabled.`);
    const verifier = newCodeVerifier();
    const flowCookie = await sealIdp(
      'flow',
      { v: verifier, intent: 'login', next: start.next, locale: start.locale },
      env().sessionSecret,
      FLOW_TTL_SECONDS,
    );
    return { url: auth.authorizeUrl(provider, await codeChallengeS256(verifier), this.config.redirectUri), flowCookie };
  }
}

export function identityProvider(): IdentityProvider {
  const e = env();
  if (e.identityProvider === 'dev') return new DevIdentityProvider();
  if (e.identityProvider === 'supabase' && e.supabase) return new SupabaseIdentityProvider(e.supabase);
  return new OidcIdentityProvider();
}
