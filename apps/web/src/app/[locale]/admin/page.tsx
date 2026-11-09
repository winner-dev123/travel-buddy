import { getTranslations, setRequestLocale } from 'next-intl/server';
import { BarChart3 } from 'lucide-react';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert, EmptyState } from '@travelbuddy/ui';

/**
 * Admin overview. Metrics come ONLY from the platform analytics API (brief §24: never generate
 * arbitrary metrics). Until that service exists (Phase 8) this page says so instead of showing numbers.
 */
export default async function AdminOverviewPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('admin.overview');
  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <h1 className="font-display text-3xl font-semibold">{t('title')}</h1>
      <Alert tone="info" title={t('noDataTitle')}>
        {t('noDataBody')}
      </Alert>
      <EmptyState icon={<BarChart3 />} title={t('metricsTitle')} description={t('metricsBody')} />
      <p className="text-sm text-muted-foreground">{t('moderationNote')}</p>
    </div>
  );
}
