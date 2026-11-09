import { type NextRequest } from 'next/server';
import { completeRegistrationSchema } from '@travelbuddy/validation';
import { writeLoginCookies } from '@/server/auth';
import { env } from '@/server/env';
import { PENDING_COOKIE, unsealIdp } from '@/server/idp-flow';
import {
  clearPendingCookie,
  currentRegistration,
  guardIdpPost,
  jsonRedirect,
  noStore,
  platformProblem,
  platformSignIn,
  problem,
} from '@/server/platform-signin';

export const dynamic = 'force-dynamic';

/**
 * Finishes registration for an IdP identity the platform does not know yet (social sign-in, or an
 * email confirmed in another browser): age gate and consent, then `POST /v1/auth/register`.
 */
export async function POST(request: NextRequest) {
  const guard = await guardIdpPost(request, completeRegistrationSchema);
  if ('response' in guard) return guard.response;
  const { auth, body: input } = guard;
  const pending = await unsealIdp('pending', request.cookies.get(PENDING_COOKIE)?.value, env().sessionSecret);
  if (!pending || pending.kind !== 'register') return problem(410, 'link_expired');

  try {
    const outcome = await platformSignIn({
      idToken: pending.t,
      locale: pending.locale,
      next: pending.next,
      userAgent: request.headers.get('user-agent'),
      registration: await currentRegistration(input.birth_date, pending.locale),
    });
    if (outcome.kind === 'needs_registration') return problem(409, 'consent_required');
    const response = jsonRedirect(outcome.redirect);
    await writeLoginCookies(response, outcome.result);
    clearPendingCookie(response);
    await auth.signOut(pending.t);
    return noStore(response);
  } catch (error) {
    return platformProblem(error);
  }
}
