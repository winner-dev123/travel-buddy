import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Container } from '@travelbuddy/ui';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'about.meta' });
  return publicPageMetadata({ siteUrl: env().siteUrl, locale, path: '/about', title: t('title'), description: t('description') });
}

export default async function AboutPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('about');
  return (
    <Container className="max-w-3xl py-16">
      <span className="eyebrow">{t('eyebrow')}</span>
      <h1 className="mt-3 font-display text-headline font-semibold">{t('title')}</h1>
      <div className="prose-travel mt-6">
        <p>{t('p1')}</p>
        <p>{t('p2')}</p>
        <h2>{t('principlesTitle')}</h2>
        <ul className="list-disc space-y-2 ps-5">
          {(['privacy', 'honesty', 'safety', 'everywhere'] as const).map((k) => (
            <li key={k}>{t(`principles.${k}`)}</li>
          ))}
        </ul>
      </div>
    </Container>
  );
}
