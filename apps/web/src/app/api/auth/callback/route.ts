import { NextResponse, type NextRequest } from 'next/server';
import { env } from '@/server/env';
import { FLOW_COOKIE, unsealIdp } from '@/server/idp-flow';
import {
  clearFlowCookie,
  completeIdpSignIn,
  noStore,
  platformErrorCode,
  supabaseAuth,
  toWebLocale,
  writePendingCookie,
} from '@/server/platform-signin';
import { safeNextPath } from '@/server/safe-redirect';
import type { SupabaseSession } from '@/server/supabase-auth';
import { localizedPath } from '@/lib/paths';

export const dynamic = 'force-dynamic';

/**
 * IdP redirect URI (`/api/auth/callback`, registered in Supabase's redirect allow-list). Handles
 * the return from Google/Apple, email-confirmation links and password-recovery links: the PKCE
 * code is exchanged server-side with the verifier from the sealed flow cookie, then the platform
 * session is created (ADR-0011, ADR-0020). Supabase tokens never reach the browser.
 */
export async function GET(request: NextRequest) {
  const auth = supabaseAuth();
  const flow = await unsealIdp('flow', request.cookies.get(FLOW_COOKIE)?.value, env().sessionSecret);
  const locale = toWebLocale(flow?.locale);
  const redirect = (target: string) => NextResponse.redirect(new URL(target, request.url), 303);
  const fail = (error: string) => {
    const response = redirect(`${localizedPath(locale, '/login')}?${new URLSearchParams({ error }).toString()}`);
    clearFlowCookie(response);
    return noStore(response);
  };

  if (!auth) return fail('provider_unavailable');
  const params = request.nextUrl.searchParams;
  if (params.get('error')) return fail(params.get('error') === 'access_denied' ? 'cancelled' : 'link_invalid');
  const code = params.get('code');
  // No flow cookie: the link was opened in another browser, or the flow expired.
  if (!code || !flow) return fail('link_invalid');

  let session: SupabaseSession;
  try {
    session = await auth.exchangeCode(code, flow.v);
  } catch {
    return fail('link_invalid');
  }

  const next = safeNextPath(flow.next);
  if (flow.intent === 'reset') {
    const response = redirect(localizedPath(locale, '/reset-password'));
    await writePendingCookie(response, session, { kind: 'reset', next, locale });
    clearFlowCookie(response);
    return noStore(response);
  }

  try {
    const response = await completeIdpSignIn(request, auth, session, { next, locale, registration: flow.reg }, redirect);
    clearFlowCookie(response);
    return response;
  } catch (error) {
    await auth.signOut(session.accessToken);
    return fail(platformErrorCode(error));
  }
}
