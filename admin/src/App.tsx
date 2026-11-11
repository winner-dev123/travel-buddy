import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router';

import { ApiError } from './api/http';
import type { Permission } from './api/types';
import { SessionProvider, useSession } from './auth/session';
import { Layout } from './components/Layout';
import { Loading } from './components/ui';
import type { ConsoleConfig } from './config';
import { I18nProvider } from './i18n/I18n';
import { AuditPage } from './pages/AuditPage';
import { BillingPage } from './pages/BillingPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OverviewPage } from './pages/OverviewPage';
import { PrivacyPage } from './pages/PrivacyPage';
import { ReportDetailPage } from './pages/ReportDetailPage';
import { ReportsPage } from './pages/ReportsPage';
import { SafetyPage } from './pages/SafetyPage';
import { SignInPage } from './pages/SignInPage';
import { StaffPage } from './pages/StaffPage';
import { UserDetailPage } from './pages/UserDetailPage';
import { UsersPage } from './pages/UsersPage';

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Client errors (403, 404, 400) won't change on a retry; network and server errors may.
        retry: (count, error) =>
          count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
        refetchOnWindowFocus: false,
        staleTime: 15_000,
      },
    },
  });
}

/** A page the signed-in role may open; others see "not found" (the API checks again). */
function Allowed({ permission, children }: { permission: Permission; children: ReactNode }) {
  const { can } = useSession();
  return can(permission) ? <>{children}</> : <NotFoundPage />;
}

export function ConsoleRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Allowed permission="users.read"><OverviewPage /></Allowed>} />
      <Route
        path="/reports"
        element={<Allowed permission="moderation.reports.read"><ReportsPage /></Allowed>}
      />
      <Route
        path="/reports/:id"
        element={<Allowed permission="moderation.reports.read"><ReportDetailPage /></Allowed>}
      />
      <Route path="/users" element={<Allowed permission="users.read"><UsersPage /></Allowed>} />
      <Route path="/users/:id" element={<Allowed permission="users.read"><UserDetailPage /></Allowed>} />
      <Route path="/billing" element={<Allowed permission="entitlements.grant"><BillingPage /></Allowed>} />
      <Route
        path="/privacy"
        element={<Allowed permission="privacy.requests.manage"><PrivacyPage /></Allowed>}
      />
      <Route path="/safety" element={<Allowed permission="safety.filters.manage"><SafetyPage /></Allowed>} />
      <Route path="/audit" element={<Allowed permission="audit.read"><AuditPage /></Allowed>} />
      <Route path="/staff" element={<Allowed permission="roles.assign"><StaffPage /></Allowed>} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

function Gate() {
  const { state } = useSession();
  const queryClient = useQueryClient();
  useEffect(() => {
    // Nothing one staff member loaded stays in memory for the next sign-in.
    if (state.status === 'signed_out') queryClient.clear();
  }, [state.status, queryClient]);
  if (state.status === 'restoring') {
    return (
      <div className="auth-screen">
        <Loading />
      </div>
    );
  }
  if (state.status === 'signed_out') return <SignInPage notice={state.notice} />;
  return (
    <Layout>
      <ConsoleRoutes />
    </Layout>
  );
}

export function App({ config }: { config: ConsoleConfig }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <SessionProvider config={config}>
          <BrowserRouter>
            <Gate />
          </BrowserRouter>
        </SessionProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
