import { type NextRequest } from 'next/server';
import { z } from 'zod';
import { emailSignInSchema } from '@travelbuddy/validation';
import { completeIdpSignIn, guardIdpPost, jsonRedirect, platformProblem, supabaseProblem } from '@/server/platform-signin';
import type { SupabaseSession } from '@/server/supabase-auth';

export const dynamic = 'force-dynamic';

const body = emailSignInSchema.extend({ next: z.string().max(2048).optional(), locale: z.string().max(10).default('en') });

/** Email + password sign-in via Supabase Auth, then the platform session (ADR-0020). */
export async function POST(request: NextRequest) {
  const guard = await guardIdpPost(request, body);
  if ('response' in guard) return guard.response;
  const { auth, body: input } = guard;

  let session: SupabaseSession;
  try {
    session = await auth.signInWithPassword(input.email, input.password);
  } catch (error) {
    return supabaseProblem(error);
  }
  try {
    return await completeIdpSignIn(request, auth, session, { next: input.next ?? '/feed', locale: input.locale }, jsonRedirect);
  } catch (error) {
    await auth.signOut(session.accessToken);
    return platformProblem(error);
  }
}
