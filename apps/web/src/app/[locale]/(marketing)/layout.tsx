import type { ReactNode } from 'react';
import { setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

/**
 * Public site frame. `setRequestLocale` must be called in every layout (they render in parallel
 * with pages); without it next-intl falls back to request headers and the whole public site
 * would silently become dynamic instead of static/ISR.
 */
export default async function MarketingLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale as LocaleCode);
  return (
    <>
      <SiteHeader />
      <main id="main">{children}</main>
      <SiteFooter />
    </>
  );
}
