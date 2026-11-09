import { setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { ComingSoon } from '@/components/coming-soon';

export default async function Page({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ComingSoon section="companions" />;
}
