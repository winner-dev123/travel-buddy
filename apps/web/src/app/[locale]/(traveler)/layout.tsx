import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { redirect } from 'next/navigation';
import { setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { TravelerShell } from '@/features/shell/traveler-shell';
import { ViewerProvider } from '@/features/shell/viewer-context';
import { localizedPath } from '@/lib/paths';
import { PRIVATE_METADATA } from '@/lib/seo';
import { getMe, isStaff, toViewerSummary } from '@/server/viewer';

export const metadata: Metadata = PRIVATE_METADATA;
export const dynamic = 'force-dynamic';

/**
 * Authenticated shell. `getMe` validates the session with the platform on every navigation that
 * renders this layout; the proxy only checks that a session cookie exists.
 */
export default async function TravelerLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as LocaleCode; // validated by the root [locale] layout
  setRequestLocale(locale);
  const me = await getMe(locale);
  if (!me.onboarding_completed) redirect(localizedPath(locale, '/onboarding'));
  return (
    <ViewerProvider viewer={toViewerSummary(me)}>
      <TravelerShell isStaff={isStaff(me.roles)}>{children}</TravelerShell>
    </ViewerProvider>
  );
}
