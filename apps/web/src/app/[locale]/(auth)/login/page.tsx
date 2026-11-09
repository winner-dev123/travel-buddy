import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert } from '@travelbuddy/ui';
import { authErrorKey } from '@/features/auth/auth-errors';
import { EmailSignInForm } from '@/features/auth/email-sign-in-form';
import { OrDivider } from '@/features/auth/or-divider';
import { ProviderButtons } from '@/features/auth/provider-buttons';
import { Link } from '@/i18n/navigation';
import { env } from '@/server/env';
import { enabledSocialProviders } from '@/server/platform-signin';
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
  const provider = env().identityProvider;
  const social = provider === 'supabase' ? await enabledSocialProviders() : [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-4xl font-semibold">{t('login.title')}</h1>
        <p className="text-muted-foreground">{t('login.subtitle')}</p>
      </div>
      {sp.reason === 'expired' ? <Alert tone="info">{t('errors.expired')}</Alert> : null}
      {sp.reason === 'reauth' ? <Alert tone="info">{t('errors.reauth')}</Alert> : null}
      {sp.reason === 'mfa' ? <Alert tone="warning">{t('errors.mfa')}</Alert> : null}
      {sp.error ? <Alert tone="danger">{t(`errors.${authErrorKey(sp.error)}`)}</Alert> : null}
      {provider === 'dev' ? <Alert tone="warning" title={t('dev.noticeTitle')}>{t('dev.noticeBody')}</Alert> : null}
      {provider === 'supabase' ? (
        <>
          <ProviderButtons intent="login" next={next} providers={social} />
          {social.length > 0 ? <OrDivider label={t('or')} /> : null}
          <EmailSignInForm next={next} />
        </>
      ) : (
        <ProviderButtons intent="login" next={next} />
      )}
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
