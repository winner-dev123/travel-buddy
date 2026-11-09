import { cookies } from 'next/headers';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert, Button } from '@travelbuddy/ui';
import { ResetPasswordForm } from '@/features/auth/reset-password-form';
import { Link } from '@/i18n/navigation';
import { env } from '@/server/env';
import { PENDING_COOKIE, unsealIdp } from '@/server/idp-flow';

/** Second half of password recovery: reached from the recovery link via `/api/auth/callback`. */
export default async function ResetPasswordPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('auth.reset');
  const pending = await unsealIdp('pending', (await cookies()).get(PENDING_COOKIE)?.value, env().sessionSecret);
  const valid = pending?.kind === 'reset';
  return (
    <div className="flex flex-col gap-5">
      <h1 className="font-display text-3xl font-semibold">{t('title')}</h1>
      {valid ? (
        <>
          <p className="text-muted-foreground">{t('body')}</p>
          <ResetPasswordForm />
        </>
      ) : (
        <>
          <Alert tone="warning">{t('expired')}</Alert>
          <Button asChild size="lg">
            <Link href="/forgot-password">{t('requestNew')}</Link>
          </Button>
        </>
      )}
    </div>
  );
}
