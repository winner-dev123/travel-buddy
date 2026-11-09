import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Container } from '@travelbuddy/ui';
import { StoreButtons } from '@/components/store-buttons';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'download.meta' });
  return publicPageMetadata({ siteUrl: env().siteUrl, locale, path: '/download', title: t('title'), description: t('description') });
}

export default async function DownloadPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('download');
  return (
    <Container className="flex max-w-3xl flex-col items-start gap-6 py-20">
      <span className="eyebrow">{t('eyebrow')}</span>
      <h1 className="font-display text-headline font-semibold">{t('title')}</h1>
      <p className="text-lg text-muted-foreground">{t('subtitle')}</p>
      <StoreButtons />
      <ul className="mt-6 grid gap-3 text-muted-foreground sm:grid-cols-2">
        {(['sync', 'offline', 'audio', 'web'] as const).map((k) => (
          <li key={k} className="rounded-card border border-border bg-surface p-4 text-sm">
            <p className="font-semibold text-foreground">{t(`points.${k}.title`)}</p>
            <p>{t(`points.${k}.body`)}</p>
          </li>
        ))}
      </ul>
    </Container>
  );
}
