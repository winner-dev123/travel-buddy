import 'server-only';
import { cache } from 'react';
import { cookies, headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { isApiError } from '@travelbuddy/api-client';
import type { Me, PlatformRole } from '@travelbuddy/domain-types';
import { env } from './env';
import { serverApi } from './platform';
import { needsRefresh, SESSION_COOKIE, unsealSession, type SessionData } from './session';

/** Minimal viewer data handed to client components (never tokens). */
export interface ViewerSummary {
  id: string;
  handle: string;
  displayName: string;
  roles: PlatformRole[];
  plan: Me['entitlements']['plan'];
  features: Me['entitlements']['features'];
  browseDestination: Me['browse_destination'];
  privacy: Me['privacy'];
  travelStyles: Me['profile']['travel_styles'];
  uiLocale: Me['preferences']['ui_locale'];
  /** Active moderation restrictions on the viewer's own account (SAFE-013), for UI messaging. */
  restrictions: NonNullable<Me['account']['restrictions']>;
}

export function toViewerSummary(me: Me): ViewerSummary {
  return {
    id: me.account.id,
    handle: me.profile.handle,
    displayName: me.profile.display_name,
    roles: me.roles,
    plan: me.entitlements.plan,
    features: me.entitlements.features,
    browseDestination: me.browse_destination,
    privacy: me.privacy,
    travelStyles: me.profile.travel_styles,
    uiLocale: me.preferences.ui_locale,
    restrictions: me.account.restrictions ?? [],
  };
}

export const getSession = cache(async (): Promise<SessionData | null> => {
  const jar = await cookies();
  return unsealSession(jar.get(SESSION_COOKIE)?.value, env().sessionSecret);
});

async function currentPath(fallback: string): Promise<string> {
  const h = await headers();
  return h.get('x-tb-pathname') ?? fallback;
}

/**
 * For dynamic (traveler/admin) server components. Redirects to login when there is no session,
 * or through the refresh route when the access token is about to expire (Server Components
 * cannot set cookies, so refresh happens in a route handler).
 */
export async function requireSession(fallbackPath = '/feed'): Promise<SessionData> {
  const session = await getSession();
  const path = await currentPath(fallbackPath);
  if (!session) redirect(`/login?next=${encodeURIComponent(path)}`);
  if (needsRefresh(session)) redirect(`/api/auth/refresh?next=${encodeURIComponent(path)}`);
  return session;
}

/** Fetches `GET /v1/users/me` for the session; handles revoked sessions. */
export const getMe = cache(async (locale: string): Promise<Me> => {
  const session = await requireSession();
  const api = await serverApi({ accessToken: session.at, locale });
  try {
    return await api.me.get();
  } catch (error) {
    if (isApiError(error) && (error.status === 401 || error.status === 403)) {
      redirect('/api/auth/logout?reason=expired');
    }
    throw error;
  }
});

/**
 * For admin data loaders: turns the platform's staff-session errors (ADM-007/008) into the right
 * sign-in prompt. Call in a `catch` around `/v1/admin/*` requests; rethrows anything else.
 */
export function redirectOnAdminAuthError(error: unknown, nextPath: string): never {
  if (isApiError(error)) {
    if (error.code === 'mfa_required') redirect(`/login?reason=mfa&next=${encodeURIComponent(nextPath)}`);
    if (error.code === 'reauthentication_required' || error.status === 401) {
      redirect(`/login?reason=reauth&next=${encodeURIComponent(nextPath)}`);
    }
  }
  throw error;
}

export const STAFF_ROLES: readonly PlatformRole[] = ['support', 'moderator', 'admin', 'superadmin'];

export function isStaff(roles: readonly PlatformRole[]): boolean {
  return roles.some((r) => STAFF_ROLES.includes(r));
}
