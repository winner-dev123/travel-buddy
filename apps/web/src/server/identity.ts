import 'server-only';
import { localizedPath } from '@/lib/paths';
import { env } from './env';

export type LoginIntent = 'login' | 'signup' | 'reset';
export type SocialProvider = 'google' | 'apple' | 'email';

export interface LoginStart {
  intent: LoginIntent;
  provider?: SocialProvider;
  next: string;
  locale: string;
}

/**
 * Identity provider port (docs/web/01 §6). Credentials, verification and password reset are owned
 * by the IdP; the web only starts flows and completes the platform session.
 */
export interface IdentityProvider {
  readonly kind: 'dev' | 'oidc';
  /** URL the browser is redirected to in order to authenticate. */
  authorizationUrl(start: LoginStart): Promise<string>;
}

/** Development/test only: a persona picker backed by the platform's dev IdP. */
class DevIdentityProvider implements IdentityProvider {
  readonly kind = 'dev' as const;
  async authorizationUrl(start: LoginStart): Promise<string> {
    const params = new URLSearchParams({ intent: start.intent, next: start.next });
    if (start.provider) params.set('provider', start.provider);
    return `${localizedPath(start.locale, '/dev/login')}?${params.toString()}`;
  }
}

/**
 * OIDC Authorization Code + PKCE (ADR-0011). NOT IMPLEMENTED YET — tracked as WEB-P1 backlog item
 * "OIDC adapter". It fails loudly rather than pretending to authenticate.
 */
class OidcIdentityProvider implements IdentityProvider {
  readonly kind = 'oidc' as const;
  async authorizationUrl(): Promise<string> {
    throw new Error('OIDC identity provider is not implemented yet (see docs/web/09-backlog.md).');
  }
}

export function identityProvider(): IdentityProvider {
  return env().identityProvider === 'dev' ? new DevIdentityProvider() : new OidcIdentityProvider();
}
