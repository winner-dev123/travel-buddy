import type { ApiClient } from '@/api';

/**
 * DEVELOPMENT ONLY: mint an ID token from the backend's dev IdP (`/v1/dev/idp/token`, which only
 * exists when the backend runs with APP_ENV=development|test). Never available in release builds.
 */
export async function mintDevIdToken(
  client: ApiClient,
  persona: { email: string; name: string },
): Promise<string> {
  if (!__DEV__) {
    throw new Error('The development identity provider is not available in release builds.');
  }
  const result = await client.post<{ id_token: string }>('/v1/dev/idp/token', {
    body: {
      sub: `dev-${persona.email.toLowerCase()}`,
      email: persona.email,
      name: persona.name,
      email_verified: true,
    },
  });
  return result.id_token;
}
