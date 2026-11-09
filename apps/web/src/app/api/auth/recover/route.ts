import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { emailSchema } from '@travelbuddy/validation';
import { env } from '@/server/env';
import { codeChallengeS256, FLOW_COOKIE, FLOW_COOKIE_PATH, FLOW_TTL_SECONDS, idpCookieOptions, newCodeVerifier, sealIdp } from '@/server/idp-flow';
import { guardIdpPost, noStore, supabaseProblem, toWebLocale } from '@/server/platform-signin';
import { SupabaseAuthError } from '@/server/supabase-auth';

export const dynamic = 'force-dynamic';

const body = z.object({ email: emailSchema, locale: z.string().max(10).default('en') });

/**
 * Requests a password-recovery email (ADR-0020). Always answers `{ ok: true }` unless rate
 * limited, so the response never reveals whether an account exists.
 */
export async function POST(request: NextRequest) {
  const guard = await guardIdpPost(request, body);
  if ('response' in guard) return guard.response;
  const { auth, body: input } = guard;
  const e = env();
  const verifier = newCodeVerifier();
  try {
    await auth.recover(input.email, await codeChallengeS256(verifier), e.supabase!.redirectUri);
  } catch (error) {
    if (error instanceof SupabaseAuthError && (error.status === 429 || error.code.startsWith('over_'))) return supabaseProblem(error);
    if (!(error instanceof SupabaseAuthError) || error.status >= 500) return supabaseProblem(error);
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(
    FLOW_COOKIE,
    await sealIdp('flow', { v: verifier, intent: 'reset', next: '/feed', locale: toWebLocale(input.locale) }, e.sessionSecret, FLOW_TTL_SECONDS),
    idpCookieOptions(e.secureCookies, FLOW_TTL_SECONDS, FLOW_COOKIE_PATH),
  );
  return noStore(response);
}
