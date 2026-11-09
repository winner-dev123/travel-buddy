import 'server-only';
import { NextResponse, type NextRequest } from 'next/server';
import type { z } from 'zod';
import { isApiError } from '@travelbuddy/api-client';
import type { AuthResult } from '@travelbuddy/domain-types';
import { localizedPath } from '@/lib/paths';
import { verifyCsrf, writeLoginCookies } from './auth';
import { env } from './env';
import {
  FLOW_COOKIE,
  FLOW_COOKIE_PATH,
  idpCookieOptions,
  PENDING_COOKIE,
  PENDING_COOKIE_PATH,
  PENDING_TTL_SECONDS,
  sealIdp,
  type PendingIdp,
} from './idp-flow';
import { getLegalVersions } from './legal';
import { serverApi } from './platform';
import { safeNextPath } from './safe-redirect';
import { createSupabaseAuth, SupabaseAuthError, type SupabaseAuth, type SupabaseSession } from './supabase-auth';

const LOCALES = ['en', 'es', 'pt-BR', 'fr', 'de'] as const;
export type WebLocale = (typeof LOCALES)[number];
export const toWebLocale = (value: string | null | undefined): WebLocale => LOCALES.find((l) => l === value) ?? 'en';

export interface Registration {
  birth_date: string;
  terms: string;
  privacy: string;
}

export type SignInOutcome = { kind: 'session'; result: AuthResult; redirect: string } | { kind: 'needs_registration' };

/** Where a signed-in user lands: onboarding first, otherwise the (validated) `next` path. */
export function landingFor(result: AuthResult, next: string): string {
  return result.user.onboarding_completed ? safeNextPath(next) : localizedPath(result.user.preferences.ui_locale, '/onboarding');
}

/**
 * Exchanges an IdP token for a platform session: `POST /v1/auth/login`, and on `404` (unknown
 * identity) `POST /v1/auth/register` when the registration details are already known. Without
 * them — or when the legal versions changed meanwhile — the user finishes registration first.
 */
export async function platformSignIn(input: {
  idToken: string;
  locale: string;
  next: string;
  userAgent?: string | null;
  registration?: Registration;
}): Promise<SignInOutcome> {
  const locale = toWebLocale(input.locale);
  const ua = input.userAgent?.slice(0, 512);
  const api = await serverApi({ locale, headers: ua ? { 'User-Agent': ua } : undefined });
  try {
    const result = await api.auth.login({ id_token: input.idToken, client: 'web' });
    return { kind: 'session', result, redirect: landingFor(result, input.next) };
  } catch (error) {
    if (!isApiError(error) || error.status !== 404) throw error;
  }
  if (!input.registration) return { kind: 'needs_registration' };
  try {
    const result = await api.auth.register({
      id_token: input.idToken,
      client: 'web',
      birth_date: input.registration.birth_date,
      accepted_terms_version: input.registration.terms,
      accepted_privacy_version: input.registration.privacy,
      locale,
    });
    return { kind: 'session', result, redirect: landingFor(result, input.next) };
  } catch (error) {
    if (isApiError(error) && error.status === 403 && error.code === 'consent_required') return { kind: 'needs_registration' };
    throw error;
  }
}

/** Registration details for the current legal documents (the user consents in the form). */
export async function currentRegistration(birth_date: string, locale: string): Promise<Registration> {
  const legal = await getLegalVersions(toWebLocale(locale));
  return { birth_date, terms: legal.terms, privacy: legal.privacy };
}

/** The configured Supabase Auth client, or null when the Supabase adapter is not active. */
export function supabaseAuth(): SupabaseAuth | null {
  const e = env();
  return e.identityProvider === 'supabase' && e.supabase ? createSupabaseAuth(e.supabase) : null;
}

export function noStore<T extends NextResponse>(response: T): T {
  response.headers.set('cache-control', 'no-store');
  return response;
}

export function problem(status: number, code: string): NextResponse {
  return noStore(NextResponse.json({ type: 'about:blank', title: code, status, code }, { status }));
}

export function clearFlowCookie(response: NextResponse): void {
  response.cookies.set(FLOW_COOKIE, '', idpCookieOptions(env().secureCookies, 0, FLOW_COOKIE_PATH));
}

export function clearPendingCookie(response: NextResponse): void {
  response.cookies.set(PENDING_COOKIE, '', idpCookieOptions(env().secureCookies, 0, PENDING_COOKIE_PATH));
}

/** Keeps the IdP token for one follow-up step, never longer than the token itself is valid. */
export async function writePendingCookie(response: NextResponse, session: SupabaseSession, pending: Omit<PendingIdp, 't' | 'e'>): Promise<void> {
  const e = env();
  const ttl = Math.min(PENDING_TTL_SECONDS, Math.floor((session.expiresAt - Date.now()) / 1000) - 30);
  if (ttl <= 0) return;
  response.cookies.set(PENDING_COOKIE, await sealIdp('pending', { ...pending, t: session.accessToken, e: session.expiresAt }, e.sessionSecret, ttl), idpCookieOptions(e.secureCookies, ttl, PENDING_COOKIE_PATH));
}

/**
 * Turns a fresh Supabase session into the response for the browser: a platform session cookie (and
 * the Supabase session signed out), or a hand-off to the finish-registration step.
 */
export async function completeIdpSignIn(
  request: NextRequest,
  auth: SupabaseAuth,
  session: SupabaseSession,
  opts: { next: string; locale: string; registration?: Registration },
  respond: (target: string) => NextResponse,
): Promise<NextResponse> {
  const outcome = await platformSignIn({
    idToken: session.accessToken,
    locale: opts.locale,
    next: opts.next,
    userAgent: request.headers.get('user-agent'),
    registration: opts.registration,
  });
  if (outcome.kind === 'needs_registration') {
    const target = `${localizedPath(toWebLocale(opts.locale), '/complete-registration')}?${new URLSearchParams({ next: safeNextPath(opts.next) }).toString()}`;
    const response = respond(target);
    await writePendingCookie(response, session, { kind: 'register', next: safeNextPath(opts.next), locale: toWebLocale(opts.locale) });
    return noStore(response);
  }
  const response = respond(outcome.redirect);
  await writeLoginCookies(response, outcome.result);
  clearPendingCookie(response);
  await auth.signOut(session.accessToken);
  return noStore(response);
}

/** Maps platform refusals to a stable error code the login page can explain. */
export function platformErrorCode(error: unknown): string {
  if (isApiError(error)) {
    if (['email_unverified', 'account_suspended', 'account_deleted', 'age_restricted', 'mfa_required'].includes(error.code)) return error.code;
    if (error.status === 401) return 'identity_rejected';
  }
  return 'provider_unavailable';
}

/** Maps Supabase Auth failures to problem responses without echoing provider messages. */
export function supabaseProblem(error: unknown): NextResponse {
  if (!(error instanceof SupabaseAuthError)) return problem(502, 'provider_unavailable');
  const code = error.code;
  if (code === 'invalid_credentials' || code === 'invalid_grant') return problem(401, 'invalid_credentials');
  if (code === 'email_not_confirmed') return problem(403, 'email_not_confirmed');
  if (code === 'signup_disabled' || code === 'email_provider_disabled') return problem(403, 'signup_disabled');
  if (code === 'user_already_exists' || code === 'email_exists') return problem(409, 'conflict');
  if (code === 'weak_password' || code === 'same_password') return problem(422, code);
  if (error.status === 429 || code.startsWith('over_')) return problem(429, 'rate_limited');
  return problem(502, 'provider_unavailable');
}

/**
 * Common guard for the Supabase form endpoints: adapter active (404 otherwise), double-submit CSRF
 * and a validated JSON body.
 */
export async function guardIdpPost<S extends z.ZodType>(
  request: NextRequest,
  schema: S,
): Promise<{ auth: SupabaseAuth; body: z.infer<S> } | { response: NextResponse }> {
  const auth = supabaseAuth();
  if (!auth) return { response: noStore(new NextResponse(null, { status: 404 })) };
  if (!verifyCsrf(request)) return { response: problem(403, 'csrf_failed') };
  const parsed = schema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) {
    return {
      response: noStore(
        NextResponse.json(
          {
            type: 'about:blank',
            title: 'validation_failed',
            status: 422,
            code: 'validation_failed',
            errors: parsed.error.issues.map((i) => ({ field: i.path.join('.'), code: 'invalid', message: i.message })),
          },
          { status: 422 },
        ),
      ),
    };
  }
  return { auth, body: parsed.data };
}

export const jsonRedirect = (target: string) => NextResponse.json({ redirect: target });

/** HTTP status for a platform refusal code from `platformErrorCode`. */
export function platformProblem(error: unknown): NextResponse {
  const code = platformErrorCode(error);
  const status = code === 'provider_unavailable' ? 502 : code === 'identity_rejected' ? 401 : 403;
  return problem(status, code);
}

/**
 * Social sign-in buttons to offer: with Supabase, only providers enabled in the project (so a
 * button never leads to a provider error page); other adapters show all of them.
 */
export async function enabledSocialProviders(): Promise<('google' | 'apple')[]> {
  const auth = supabaseAuth();
  if (!auth) return ['google', 'apple'];
  try {
    const { providers } = await auth.settings();
    return (['google', 'apple'] as const).filter((p) => providers[p]);
  } catch {
    return [];
  }
}
