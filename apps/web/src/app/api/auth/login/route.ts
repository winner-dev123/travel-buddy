import { NextResponse, type NextRequest } from 'next/server';
import { env } from '@/server/env';
import { FLOW_COOKIE, FLOW_COOKIE_PATH, FLOW_TTL_SECONDS, idpCookieOptions } from '@/server/idp-flow';
import { identityProvider, type LoginIntent, type SocialProvider } from '@/server/identity';
import { safeNextPath } from '@/server/safe-redirect';
import { localizedPath } from '@/lib/paths';

export const dynamic = 'force-dynamic';

const INTENTS: LoginIntent[] = ['login', 'signup', 'reset'];
const PROVIDERS: SocialProvider[] = ['google', 'apple', 'email'];

/** Starts an IdP flow. `GET /api/auth/login?intent=login|signup|reset&provider=&next=&locale=` */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const intent = (INTENTS as string[]).includes(params.get('intent') ?? '') ? (params.get('intent') as LoginIntent) : 'login';
  const provider = (PROVIDERS as string[]).includes(params.get('provider') ?? '') ? (params.get('provider') as SocialProvider) : undefined;
  const locale = params.get('locale') ?? 'en';
  const next = safeNextPath(params.get('next'));
  try {
    const start = await identityProvider().start({ intent, provider, next, locale });
    const response = NextResponse.redirect(new URL(start.url, request.url), 303);
    if (start.flowCookie) {
      response.cookies.set(FLOW_COOKIE, start.flowCookie, idpCookieOptions(env().secureCookies, FLOW_TTL_SECONDS, FLOW_COOKIE_PATH));
    }
    response.headers.set('cache-control', 'no-store');
    return response;
  } catch {
    return NextResponse.redirect(new URL(`${localizedPath(locale, '/login')}?error=provider_unavailable`, request.url), 303);
  }
}
