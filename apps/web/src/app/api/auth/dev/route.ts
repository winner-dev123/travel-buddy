import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { isApiError } from '@travelbuddy/api-client';
import { registerSchema } from '@travelbuddy/validation';
import { env } from '@/server/env';
import { serverApi } from '@/server/platform';
import { verifyCsrf, writeLoginCookies } from '@/server/auth';
import { safeNextPath } from '@/server/safe-redirect';
import { localizedPath } from '@/lib/paths';

export const dynamic = 'force-dynamic';

/** Current legal document versions accepted at registration (to be served by the platform). */
const TERMS_VERSION = '2026-11';
const PRIVACY_VERSION = '2026-11';

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
  const api = await serverApi({ locale: input.locale });

  try {
    let result;
    if (input.mode === 'login') {
      const { id_token } = await api.auth.devIdpToken({ sub: input.sub, email: input.email, name: input.name });
      result = await api.auth.login({ id_token, client: 'web' });
    } else {
      const sub = `dev:${input.email}`;
      const { id_token } = await api.auth.devIdpToken({ sub, email: input.email, name: input.display_name });
      result = await api.auth.register({
        id_token,
        client: 'web',
        birth_date: input.birth_date,
        accepted_terms_version: TERMS_VERSION,
        accepted_privacy_version: PRIVACY_VERSION,
        locale: (['en', 'es', 'pt-BR', 'fr', 'de'] as const).find((l) => l === input.locale) ?? 'en',
      });
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
