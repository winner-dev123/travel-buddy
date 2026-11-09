import { type NextRequest } from 'next/server';
import { resetPasswordSchema } from '@travelbuddy/validation';
import { env } from '@/server/env';
import { PENDING_COOKIE, unsealIdp } from '@/server/idp-flow';
import { completeIdpSignIn, guardIdpPost, jsonRedirect, platformProblem, problem, supabaseProblem } from '@/server/platform-signin';

export const dynamic = 'force-dynamic';

/** Sets a new password after a recovery link (ADR-0020), then signs the user in. */
export async function POST(request: NextRequest) {
  const guard = await guardIdpPost(request, resetPasswordSchema);
  if ('response' in guard) return guard.response;
  const { auth, body: input } = guard;
  const pending = await unsealIdp('pending', request.cookies.get(PENDING_COOKIE)?.value, env().sessionSecret);
  if (!pending || pending.kind !== 'reset') return problem(410, 'link_expired');

  try {
    await auth.updatePassword(pending.t, input.password);
  } catch (error) {
    return supabaseProblem(error);
  }
  const session = { accessToken: pending.t, expiresAt: pending.e };
  try {
    return await completeIdpSignIn(request, auth, session, { next: pending.next, locale: pending.locale }, jsonRedirect);
  } catch (error) {
    await auth.signOut(session.accessToken);
    return platformProblem(error);
  }
}
