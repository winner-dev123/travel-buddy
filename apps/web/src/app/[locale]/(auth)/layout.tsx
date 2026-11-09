import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { DestinationArt } from '@/components/destination-art';
import { LocaleSwitcher } from '@/components/locale-switcher';
import { Logo } from '@/components/logo';
import { ThemeToggle } from '@/components/theme-toggle';
import { Link } from '@/i18n/navigation';
import { PRIVATE_METADATA } from '@/lib/seo';

export const metadata: Metadata = PRIVATE_METADATA;

export default async function AuthLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  setRequestLocale((await params).locale as LocaleCode);
  const t = await getTranslations('auth');
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.1fr]">
      <div className="relative hidden overflow-hidden lg:block" aria-hidden="true">
        <DestinationArt seed="auth-panel" categories={['beaches']} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
        <p className="absolute inset-x-10 bottom-12 font-display text-4xl leading-tight font-semibold text-white">{t('panelQuote')}</p>
      </div>
      <div className="flex flex-col">
        <header className="flex items-center justify-between px-6 py-5">
          <Link href="/" aria-label={t('backHome')}>
            <Logo />
          </Link>
          <div className="flex items-center gap-3">
            <LocaleSwitcher />
            <ThemeToggle />
          </div>
        </header>
        <main id="main" className="flex flex-1 items-center justify-center px-6 py-10">
          <div className="w-full max-w-md">{children}</div>
        </main>
      </div>
    </div>
  );
}
