import createMiddleware from 'next-intl/middleware';
import { NextRequest, NextResponse } from 'next/server';
import { LOCALES } from '@travelbuddy/i18n';
import { routing } from './i18n/routing';
import { env } from './server/env-core';

/**
 * Runs before every page request:
 *  1. session-presence gating (validity is checked again by layouts and by the platform);
 *  2. locale routing (next-intl);
 *  3. Content-Security-Policy — nonce-based for dynamic routes, and `'unsafe-inline'` scripts only
 *     for statically generated public pages, where a per-request nonce is impossible
 *     (docs/web/08 §7);
 *  4. seeding the CSRF double-submit cookie (dynamic routes only — public pages stay cookie-free
 *     so the CDN can cache them).
 */
const handleI18nRouting = createMiddleware(routing);

const PROTECTED =
  /^\/(feed|posts|explore|saved|assistant|trips|companions|messages|groups|tours|profile|notifications|membership|settings|onboarding|admin)(\/|$)/;
const AUTH_ONLY_FOR_GUESTS = /^\/(login|register)(\/|$)/;
const OTHER_DYNAMIC = /^\/(dev|forgot-password|verify-email)(\/|$)/;

function stripLocale(pathname: string): { locale: string; prefix: string; rest: string } {
  const lower = pathname.toLowerCase();
  for (const l of LOCALES) {
    if (l.prefix && (lower === l.prefix || lower.startsWith(`${l.prefix}/`))) {
      return { locale: l.code, prefix: l.prefix, rest: pathname.slice(l.prefix.length) || '/' };
    }
  }
  return { locale: 'en', prefix: '', rest: pathname || '/' };
}

function originOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

function buildCsp(nonce: string | null, isDevLike: boolean, connectExtra: string[]): string {
  const devEval = process.env.NODE_ENV === 'development' ? " 'unsafe-eval'" : '';
  const scriptSrc = nonce ? `'self' 'nonce-${nonce}'${devEval}` : `'self' 'unsafe-inline'${devEval}`;
  const connect = ["'self'", ...connectExtra, ...(process.env.NODE_ENV === 'development' ? ['ws://localhost:*', 'ws://127.0.0.1:*'] : [])];
  return [
    `default-src 'self'`,
    `script-src ${scriptSrc}`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data: blob: https:`,
    `font-src 'self' data:`,
    `connect-src ${connect.join(' ')}`,
    `worker-src 'self' blob:`,
    `media-src 'self' blob: https:`,
    `frame-src 'none'`,
    `frame-ancestors 'none'`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    ...(isDevLike ? [] : ['upgrade-insecure-requests']),
  ].join('; ');
}

function randomToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Buffer.from(bytes).toString('base64url');
}

export function proxy(request: NextRequest) {
  const e = env();
  const { pathname, search } = request.nextUrl;
  const { prefix, rest } = stripLocale(pathname);
  const hasSession = request.cookies.has('tb_session');
  const localized = (path: string) => new URL(prefix ? `${prefix}${path === '/' ? '' : path}` || '/' : path, request.url);

  if (rest.startsWith('/admin') && e.adminAllowedHosts.length > 0) {
    const host = (request.headers.get('host') ?? '').toLowerCase();
    if (!e.adminAllowedHosts.includes(host)) return new NextResponse(null, { status: 404 });
  }
  if (PROTECTED.test(rest) && !hasSession) {
    const url = localized('/login');
    url.searchParams.set('next', `${pathname}${search}`);
    return NextResponse.redirect(url, 307);
  }
  if (hasSession && (rest === '/' || AUTH_ONLY_FOR_GUESTS.test(rest))) {
    return NextResponse.redirect(localized('/feed'), 307);
  }

  const dynamicRoute = PROTECTED.test(rest) || AUTH_ONLY_FOR_GUESTS.test(rest) || OTHER_DYNAMIC.test(rest);
  const nonce = dynamicRoute ? Buffer.from(crypto.randomUUID()).toString('base64') : null;
  const mapOrigin = originOf(e.mapStyleUrl) ?? (e.isDevLike ? 'https://demotiles.maplibre.org' : null);
  const csp = buildCsp(nonce, e.isDevLike, [originOf(e.realtimeUrl), mapOrigin].filter((v): v is string => Boolean(v)));

  const forwarded = new Headers(request.headers);
  forwarded.set('x-tb-pathname', `${pathname}${search}`);
  if (nonce) {
    forwarded.set('x-nonce', nonce);
    forwarded.set('content-security-policy', csp);
  }
  const response = handleI18nRouting(new NextRequest(request, { headers: forwarded }));

  response.headers.set('content-security-policy', csp);
  if (dynamicRoute) response.headers.set('x-robots-tag', 'noindex, nofollow');
  // Only dynamic (never CDN-cached) responses may carry Set-Cookie; they are also the only pages
  // that perform mutations, so they are where the CSRF double-submit token is needed.
  if (dynamicRoute && !request.cookies.has('tb_csrf')) {
    response.cookies.set('tb_csrf', randomToken(), {
      httpOnly: false,
      sameSite: 'strict',
      secure: e.secureCookies,
      path: '/',
      maxAge: 60 * 60 * 24 * 30,
    });
  }
  return response;
}

export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\.(?:ico|png|jpg|jpeg|gif|svg|webp|avif|js|mjs|css|txt|xml|json|webmanifest|map|woff2?)$).*)'],
};
