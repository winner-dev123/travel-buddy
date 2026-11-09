import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { FeedView } from '@/features/feed/feed-view';

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'feed' });
  return { title: t('metaTitle') };
}

export default async function FeedPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return (
    <FeedView />
  );
}
