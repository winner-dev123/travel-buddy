import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { vi } from 'vitest';

import type { AdminApi } from '../api/admin';
import type { Me, Permission, PlatformRole } from '../api/types';
import { SessionTestProvider, type Session } from '../auth/session';
import { I18nProvider, type Locale } from '../i18n/I18n';

export const ROLE_PERMISSIONS: Record<PlatformRole, Permission[]> = {
  support: ['users.read', 'moderation.reports.read', 'moderation.actions.read'],
  moderator: [
    'users.read',
    'moderation.reports.read',
    'moderation.actions.read',
    'moderation.reports.manage',
    'moderation.actions.write',
    'users.suspend',
    'content.rewards.review',
  ],
  admin: [
    'users.read',
    'moderation.reports.read',
    'moderation.actions.read',
    'moderation.reports.manage',
    'moderation.actions.write',
    'users.suspend',
    'content.rewards.review',
    'users.read_sensitive',
    'users.ban',
    'content.destinations.write',
    'content.feature',
    'entitlements.grant',
    'audit.read',
    'privacy.requests.manage',
    'safety.filters.manage',
  ],
  superadmin: [],
};
ROLE_PERMISSIONS.superadmin = [...ROLE_PERMISSIONS.admin, 'billing.configure', 'roles.assign'];

export const ME_ID = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b';

export function staffMe(role: PlatformRole): Me {
  return {
    account: { id: ME_ID, email: 'ana@example.com', status: 'active', primary_locale: 'en' },
    profile: { handle: 'ana', display_name: 'Ana Souza' },
    roles: [role],
    permissions: ROLE_PERMISSIONS[role],
  };
}

/** Every API call is a vi.fn; tests set the ones they need. */
export function fakeApi(overrides: Partial<Record<keyof AdminApi, unknown>> = {}): AdminApi {
  const names: (keyof AdminApi)[] = [
    'me',
    'overview',
    'ops',
    'reports',
    'report',
    'assignReport',
    'resolveReport',
    'actions',
    'createAction',
    'users',
    'user',
    'suspend',
    'reinstate',
    'grants',
    'grant',
    'revokeGrant',
    'assignRole',
    'removeRole',
    'transactions',
    'products',
    'updateProduct',
    'dataRequests',
    'resolveDataRequest',
    'auditLogs',
    'messageFilter',
    'updateMessageFilter',
  ];
  const api = Object.fromEntries(
    names.map((name) => [name, vi.fn(() => new Promise(() => undefined))]),
  ) as unknown as AdminApi;
  return Object.assign(api, overrides);
}

export function renderConsole(
  ui: ReactElement,
  {
    role = 'admin',
    api = fakeApi(),
    route = '/',
    reason = 'Reviewing the report queue today',
    locale = 'en',
    session = {},
  }: {
    role?: PlatformRole;
    api?: AdminApi;
    route?: string;
    reason?: string | null;
    locale?: Locale;
    session?: Partial<Session>;
  } = {},
) {
  const me = staffMe(role);
  const value: Session = {
    state: { status: 'signed_in', me },
    api,
    config: { apiBaseUrl: 'https://api.test', firebaseApiKey: 'test-key', environmentLabel: 'staging' },
    signIn: vi.fn(async () => 'ok' as const),
    isStaff: vi.fn(async () => true),
    signOut: vi.fn(async () => undefined),
    reason,
    setReason: vi.fn(),
    can: (permission) => me.permissions?.includes(permission) ?? false,
    ...session,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(
    <I18nProvider locale={locale}>
      <QueryClientProvider client={client}>
        <SessionTestProvider value={value}>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </SessionTestProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
  return { ...result, api, session: value };
}

export function page<T>(data: T[], nextCursor: string | null = null) {
  return { data, page: { next_cursor: nextCursor, has_more: nextCursor !== null } };
}
