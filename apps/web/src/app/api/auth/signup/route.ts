import { type NextRequest } from 'next/server';
import { z } from 'zod';
import { passwordRegisterSchema } from '@travelbuddy/validation';
import { env } from '@/server/env';
import { codeChallengeS256, FLOW_COOKIE, FLOW_COOKIE_PATH, FLOW_TTL_SECONDS, idpCookieOptions, newCodeVerifier, sealIdp } from '@/server/idp-flow';
import {
  completeIdpSignIn,
  currentRegistration,
  guardIdpPost,
  jsonRedirect,
  noStore,
  platformProblem,
  supabaseProblem,
  toWebLocale,
} from '@/server/platform-signin';
import { safeNextPath } from '@/server/safe-redirect';
import type { SupabaseSession } from '@/server/supabase-auth';
import { localizedPath } from '@/lib/paths';

export const dynamic = 'force-dynamic';

const body = passwordRegisterSchema.extend({ next: z.string().max(2048).optional(), locale: z.string().max(10).default('en') });

/**
 * Email + password registration (ADR-0020). The age gate and consent are validated before any
 * identity is created (AUTH-008). When Supabase sends a confirmation email, its link returns to
 * the callback with a PKCE code, and the registration details travel in the sealed flow cookie.
 */
export async function POST(request: NextRequest) {
  const guard = await guardIdpPost(request, body);
  if ('response' in guard) return guard.response;
  const { auth, body: input } = guard;
  const e = env();
  const locale = toWebLocale(input.locale);
  const next = safeNextPath(input.next);
  const registration = await currentRegistration(input.birth_date, locale);
  const verifier = newCodeVerifier();

  let session: SupabaseSession | null;
  try {
    session = await auth.signUp({
      email: input.email,
      password: input.password,
      name: input.display_name,
      codeChallenge: await codeChallengeS256(verifier),
      redirectTo: e.supabase!.redirectUri,
    });
  } catch (error) {
    return supabaseProblem(error);
  }

  if (session) {
    try {
      return await completeIdpSignIn(request, auth, session, { next, locale, registration }, jsonRedirect);
    } catch (error) {
      await auth.signOut(session.accessToken);
      return platformProblem(error);
    }
  }

  const response = jsonRedirect(localizedPath(locale, '/verify-email'));
  response.cookies.set(
    FLOW_COOKIE,
    await sealIdp('flow', { v: verifier, intent: 'signup', next, locale, reg: registration }, e.sessionSecret, FLOW_TTL_SECONDS),
    idpCookieOptions(e.secureCookies, FLOW_TTL_SECONDS, FLOW_COOKIE_PATH),
  );
  return noStore(response);
}
