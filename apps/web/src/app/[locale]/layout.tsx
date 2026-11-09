import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { notFound } from 'next/navigation';
import { Fraunces, Plus_Jakarta_Sans } from 'next/font/google';
import { hasLocale, NextIntlClientProvider } from 'next-intl';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { localeInfo } from '@travelbuddy/i18n';
import { routing } from '@/i18n/routing';
import { Providers } from '@/components/providers';
import { EnvironmentBanner } from '@/components/environment-banner';
import { env } from '@/server/env';
import '@/styles/globals.css';

const fraunces = Fraunces({ subsets: ['latin', 'latin-ext'], variable: '--font-fraunces', display: 'swap', axes: ['opsz'] });
const jakarta = Plus_Jakarta_Sans({ subsets: ['latin', 'latin-ext'], variable: '--font-jakarta', display: 'swap' });

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  const t = await getTranslations({ locale, namespace: 'meta' });
  return {
    metadataBase: new URL(env().siteUrl),
    title: { default: t('defaultTitle'), template: `%s · ${t('siteName')}` },
    description: t('defaultDescription'),
    applicationName: t('siteName'),
    openGraph: { siteName: t('siteName'), type: 'website', locale: localeInfo(locale).bcp47.replace('-', '_') },
    twitter: { card: 'summary_large_image' },
    formatDetection: { telephone: false },
  };
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fafaf7' },
    { media: '(prefers-color-scheme: dark)', color: '#0e1a1d' },
  ],
  width: 'device-width',
  initialScale: 1,
};

export default async function LocaleLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const info = localeInfo(locale);
  const t = await getTranslations({ locale, namespace: 'common' });
  const e = env();

  return (
    <html lang={info.bcp47} dir={info.dir} className={`${fraunces.variable} ${jakarta.variable}`} suppressHydrationWarning>
      <head>
        {/* Blocking, same-origin theme bootstrap (CSP-safe; see public/theme-init.js). */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/theme-init.js" />
      </head>
      <body className="min-h-dvh bg-background text-foreground">
        <a href="#main" className="skip-link">
          {t('skipToContent')}
        </a>
        <NextIntlClientProvider>
          <Providers>
            {e.apiMode === 'mock' ? <EnvironmentBanner /> : null}
            {children}
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
