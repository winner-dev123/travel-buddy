import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Button } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';

/** Password reset is owned by the identity provider (doc 02 §8); this page hands off to it. */
export default async function ForgotPasswordPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('auth.forgot');
  return (
    <div className="flex flex-col gap-5">
      <h1 className="font-display text-3xl font-semibold">{t('title')}</h1>
      <p className="text-muted-foreground">{t('body')}</p>
      <Button asChild size="lg">
        <a href={`/api/auth/login?${new URLSearchParams({ intent: 'reset', locale, next: '/feed' }).toString()}`}>{t('cta')}</a>
      </Button>
      <Link href="/login" className="text-sm text-primary hover:underline">
        {t('back')}
      </Link>
    </div>
  );
}
