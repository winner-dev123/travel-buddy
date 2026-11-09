import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { isApiError } from '@travelbuddy/api-client';
import { registerSchema } from '@travelbuddy/validation';
import { env } from '@/server/env';
import { getLegalVersions } from '@/server/legal';
import { serverApi } from '@/server/platform';
import { verifyCsrf, writeLoginCookies } from '@/server/auth';
import { safeNextPath } from '@/server/safe-redirect';
import { localizedPath } from '@/lib/paths';

export const dynamic = 'force-dynamic';

/** Birth date used only when a development persona must be registered in a platform dev database. */
const DEV_PERSONA_BIRTH_DATE = '1990-01-01';

const loginBody = z.object({
  mode: z.literal('login'),
  sub: z.string().min(1).max(200),
  email: z.string().email(),
  name: z.string().max(80).optional(),
  next: z.string().optional(),
  locale: z.string().max(10).default('en'),
});

const registerBody = registerSchema.extend({
  mode: z.literal('register'),
  next: z.string().optional(),
  locale: z.string().max(10).default('en'),
});

/**
 * Development identity sign-in (ADR-0011). Exists only when TB_IDENTITY_PROVIDER=dev, which the
 * environment check restricts to APP_ENV development/test. Uses the platform dev IdP and then
 * the production login/register path, so the platform session is real (or mock-real).
 */
export async function POST(request: NextRequest) {
  const e = env();
  if (e.identityProvider !== 'dev' || !e.isDevLike) return new NextResponse(null, { status: 404 });
  if (!verifyCsrf(request)) {
    return NextResponse.json({ code: 'csrf_failed', title: 'CSRF check failed', status: 403 }, { status: 403 });
  }

  const json = (await request.json().catch(() => null)) as unknown;
  const parsed = z.discriminatedUnion('mode', [loginBody, registerBody]).safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      {
        code: 'validation_failed',
        title: 'Validation failed',
        status: 422,
        errors: parsed.error.issues.map((i) => ({ field: i.path.join('.'), code: 'invalid', message: i.message })),
      },
      { status: 422 },
    );
  }
  const input = parsed.data;
  // The platform derives the session's device name from the User-Agent when `device` is omitted.
  const userAgent = request.headers.get('user-agent')?.slice(0, 512);
  const api = await serverApi({ locale: input.locale, headers: userAgent ? { 'User-Agent': userAgent } : undefined });
  const locale = (['en', 'es', 'pt-BR', 'fr', 'de'] as const).find((l) => l === input.locale) ?? 'en';
  const legal = await getLegalVersions(locale);
  const register = (id_token: string, birth_date: string) =>
    api.auth.register({
      id_token,
      client: 'web',
      birth_date,
      accepted_terms_version: legal.terms,
      accepted_privacy_version: legal.privacy,
      locale,
    });

  try {
    let result;
    if (input.mode === 'login') {
      const identity = { sub: input.sub, email: input.email, name: input.name };
      const { id_token } = await api.auth.devIdpToken(identity);
      try {
        result = await api.auth.login({ id_token, client: 'web' });
      } catch (error) {
        // Contract: unknown identity → 404, call register. Seeded personas exist in the mock but not
        // yet in a fresh platform dev database, so dev tooling registers them (adult test identities).
        if (!isApiError(error) || error.status !== 404) throw error;
        const fresh = await api.auth.devIdpToken(identity);
        result = await register(fresh.id_token, DEV_PERSONA_BIRTH_DATE);
      }
    } else {
      const sub = `dev:${input.email}`;
      const { id_token } = await api.auth.devIdpToken({ sub, email: input.email, name: input.display_name });
      result = await register(id_token, input.birth_date);
    }
    const target = result.user.onboarding_completed
      ? safeNextPath(input.next)
      : localizedPath(result.user.preferences.ui_locale, '/onboarding');
    const response = NextResponse.json({ redirect: target, onboarding_completed: result.user.onboarding_completed });
    await writeLoginCookies(response, result);
    response.headers.set('cache-control', 'no-store');
    return response;
  } catch (error) {
    if (isApiError(error)) {
      return NextResponse.json(error.problem, { status: error.status || 502 });
    }
    throw error;
  }
}
