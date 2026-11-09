import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert } from '@travelbuddy/ui';
import { ProviderButtons } from '@/features/auth/provider-buttons';
import { Link } from '@/i18n/navigation';
import { env } from '@/server/env';
import { safeNextPath } from '@/server/safe-redirect';

export default async function LoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: LocaleCode }>;
  searchParams: Promise<{ next?: string; error?: string; reason?: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const sp = await searchParams;
  const t = await getTranslations('auth');
  const next = safeNextPath(sp.next);
  const devIdentity = env().identityProvider === 'dev';

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-4xl font-semibold">{t('login.title')}</h1>
        <p className="text-muted-foreground">{t('login.subtitle')}</p>
      </div>
      {sp.reason === 'expired' ? <Alert tone="info">{t('errors.expired')}</Alert> : null}
      {sp.reason === 'reauth' ? <Alert tone="info">{t('errors.reauth')}</Alert> : null}
      {sp.reason === 'mfa' ? <Alert tone="warning">{t('errors.mfa')}</Alert> : null}
      {sp.error === 'provider_unavailable' ? <Alert tone="danger">{t('errors.providerUnavailable')}</Alert> : null}
      {devIdentity ? <Alert tone="warning" title={t('dev.noticeTitle')}>{t('dev.noticeBody')}</Alert> : null}
      <ProviderButtons intent="login" next={next} />
      <div className="flex flex-col gap-2 text-sm">
        <a href={`/api/auth/login?${new URLSearchParams({ intent: 'reset', next, locale }).toString()}`} className="text-primary hover:underline">
          {t('login.forgot')}
        </a>
        <p className="text-muted-foreground">
          {t('login.noAccount')}{' '}
          <Link href={`/register?next=${encodeURIComponent(next)}`} className="font-semibold text-primary hover:underline">
            {t('login.createAccount')}
          </Link>
        </p>
      </div>
    </div>
  );
}
