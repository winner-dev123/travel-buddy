import { cookies } from 'next/headers';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert, Button } from '@travelbuddy/ui';
import { CompleteRegistrationForm } from '@/features/auth/complete-registration-form';
import { Link } from '@/i18n/navigation';
import { env } from '@/server/env';
import { PENDING_COOKIE, unsealIdp } from '@/server/idp-flow';

/**
 * Finish registration: the identity provider confirmed who the user is, but the platform has no
 * account yet, so it still needs the age gate and consent (AUTH-008) before `POST /v1/auth/register`.
 */
export default async function CompleteRegistrationPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('auth.complete');
  const pending = await unsealIdp('pending', (await cookies()).get(PENDING_COOKIE)?.value, env().sessionSecret);
  const valid = pending?.kind === 'register';
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-4xl font-semibold">{t('title')}</h1>
        <p className="text-muted-foreground">{t('subtitle')}</p>
      </div>
      {valid ? (
        <CompleteRegistrationForm />
      ) : (
        <>
          <Alert tone="warning">{t('expired')}</Alert>
          <Button asChild size="lg">
            <Link href="/login">{t('backToLogin')}</Link>
          </Button>
        </>
      )}
    </div>
  );
}
