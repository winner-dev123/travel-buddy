import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert } from '@travelbuddy/ui';
import { OrDivider } from '@/features/auth/or-divider';
import { ProviderButtons } from '@/features/auth/provider-buttons';
import { RegisterForm } from '@/features/auth/register-form';
import { Link } from '@/i18n/navigation';
import { env } from '@/server/env';
import { enabledSocialProviders } from '@/server/platform-signin';
import { safeNextPath } from '@/server/safe-redirect';

export default async function RegisterPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: LocaleCode }>;
  searchParams: Promise<{ next?: string }>;
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
        <h1 className="font-display text-4xl font-semibold">{t('register.title')}</h1>
        <p className="text-muted-foreground">{t('register.subtitle')}</p>
      </div>
      {provider === 'dev' ? (
        <>
          <Alert tone="warning" title={t('dev.noticeTitle')}>
            {t('dev.registerNotice')}
          </Alert>
          <RegisterForm next={next} />
        </>
      ) : provider === 'supabase' ? (
        <>
          <ProviderButtons intent="signup" next={next} providers={social} />
          {social.length > 0 ? <OrDivider label={t('or')} /> : null}
          <RegisterForm next={next} withPassword />
        </>
      ) : (
        <ProviderButtons intent="signup" next={next} />
      )}
      <p className="text-sm text-muted-foreground">
        {t('register.haveAccount')}{' '}
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-primary hover:underline">
          {t('register.signIn')}
        </Link>
      </p>
    </div>
  );
}
