import { getTranslations, setRequestLocale } from 'next-intl/server';
import { Construction } from 'lucide-react';
import type { LocaleCode } from '@travelbuddy/i18n';
import { EmptyState } from '@travelbuddy/ui';

/** Admin sections scheduled for Phase 8 render an honest placeholder inside the admin shell. */
export default async function AdminSectionPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('admin.comingSoon');
  return <EmptyState className="max-w-3xl" icon={<Construction />} title={t('title')} description={t('body')} />;
}
