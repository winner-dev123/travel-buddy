import { notFound } from 'next/navigation';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert } from '@travelbuddy/ui';
import { DevPersonaPicker } from '@/features/auth/dev-persona-picker';
import { Link } from '@/i18n/navigation';
import { env } from '@/server/env';
import { safeNextPath } from '@/server/safe-redirect';

/** Development identity provider. 404 unless TB_IDENTITY_PROVIDER=dev in development/test. */
export default async function DevLoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: LocaleCode }>;
  searchParams: Promise<{ next?: string; intent?: string }>;
}) {
  const e = env();
  if (e.identityProvider !== 'dev' || !e.isDevLike) notFound();
  const { locale } = await params;
  setRequestLocale(locale);
  const sp = await searchParams;
  const t = await getTranslations('auth.dev');
  const { listDevPersonas } = await import('@travelbuddy/api-client/mock');

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-3xl font-semibold">{t('title')}</h1>
        <p className="text-muted-foreground">{t('subtitle')}</p>
      </div>
      <Alert tone="warning" title={t('noticeTitle')}>
        {t('noticeBody')}
      </Alert>
      <DevPersonaPicker personas={listDevPersonas()} next={safeNextPath(sp.next)} />
      <p className="text-sm text-muted-foreground">
        {t('orRegister')}{' '}
        <Link href={`/register?next=${encodeURIComponent(safeNextPath(sp.next))}`} className="font-semibold text-primary hover:underline">
          {t('registerLink')}
        </Link>
      </p>
    </div>
  );
}
