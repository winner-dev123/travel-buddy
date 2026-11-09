import { getTranslations, setRequestLocale } from 'next-intl/server';
import { MailCheck } from 'lucide-react';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Button } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';

/** Email verification is performed by the identity provider; this page explains the next step. */
export default async function VerifyEmailPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('auth.verify');
  return (
    <div className="flex flex-col items-start gap-5">
      <span className="flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary">
        <MailCheck className="size-6" aria-hidden="true" />
      </span>
      <h1 className="font-display text-3xl font-semibold">{t('title')}</h1>
      <p className="text-muted-foreground">{t('body')}</p>
      <Button asChild>
        <Link href="/login">{t('cta')}</Link>
      </Button>
    </div>
  );
}
