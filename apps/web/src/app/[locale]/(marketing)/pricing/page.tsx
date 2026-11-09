import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { Check, Minus } from 'lucide-react';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert, Badge, Button, Card, Container } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';

export const revalidate = 3600;

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'pricing.meta' });
  return publicPageMetadata({ siteUrl: env().siteUrl, locale, path: '/pricing', title: t('title'), description: t('description') });
}

/**
 * Plan comparison from doc 07 §3 (feature names only — numbers are platform configuration and
 * prices come from Stripe Prices via the billing API at checkout; nothing is hard-coded here).
 */
const ROWS = ['explore', 'stories', 'companions', 'messaging', 'joinGroups', 'createGroups', 'challenges', 'ai', 'premiumGuides', 'offline'] as const;
const FREE: Record<(typeof ROWS)[number], boolean | 'limited'> = {
  explore: true,
  stories: true,
  companions: true,
  messaging: true,
  joinGroups: true,
  createGroups: false,
  challenges: false,
  ai: 'limited',
  premiumGuides: false,
  offline: 'limited',
};

export default async function PricingPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('pricing');

  const cell = (value: boolean | 'limited') =>
    value === true ? (
      <Check className="mx-auto size-5 text-primary" aria-label={t('included')} />
    ) : value === 'limited' ? (
      <span className="text-sm font-semibold text-muted-foreground">{t('limited')}</span>
    ) : (
      <Minus className="mx-auto size-5 text-muted-foreground" aria-label={t('notIncluded')} />
    );

  return (
    <Container className="py-14">
      <div className="mx-auto flex max-w-2xl flex-col items-center gap-4 text-center">
        <span className="eyebrow">{t('eyebrow')}</span>
        <h1 className="font-display text-headline font-semibold">{t('title')}</h1>
        <p className="text-lg text-muted-foreground">{t('subtitle')}</p>
      </div>

      <div className="mx-auto mt-12 grid max-w-4xl gap-6 md:grid-cols-2">
        <Card className="flex flex-col gap-4 p-7">
          <h2 className="font-display text-2xl font-semibold">{t('free.name')}</h2>
          <p className="text-muted-foreground">{t('free.description')}</p>
          <Button asChild variant="secondary" className="mt-auto">
            <Link href="/register">{t('free.cta')}</Link>
          </Button>
        </Card>
        <Card className="relative flex flex-col gap-4 border-primary p-7 ring-2 ring-primary">
          <Badge tone="accent" className="absolute end-5 top-5">
            {t('premium.badge')}
          </Badge>
          <h2 className="font-display text-2xl font-semibold">{t('premium.name')}</h2>
          <p className="text-muted-foreground">{t('premium.description')}</p>
          <p className="text-sm text-muted-foreground">{t('premium.priceNote')}</p>
          <Button asChild variant="primary" className="mt-auto">
            <Link href="/membership/checkout">{t('premium.cta')}</Link>
          </Button>
        </Card>
      </div>

      <div className="mx-auto mt-12 max-w-4xl overflow-x-auto rounded-card border border-border bg-surface">
        <table className="w-full min-w-[32rem] text-start">
          <caption className="sr-only">{t('compare')}</caption>
          <thead className="border-b border-border bg-surface-muted/60">
            <tr>
              <th scope="col" className="px-5 py-3 text-start text-sm font-semibold">
                {t('feature')}
              </th>
              <th scope="col" className="px-5 py-3 text-center text-sm font-semibold">
                {t('free.name')}
              </th>
              <th scope="col" className="px-5 py-3 text-center text-sm font-semibold">
                {t('premium.name')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {ROWS.map((row) => (
              <tr key={row}>
                <th scope="row" className="px-5 py-3 text-start text-sm font-medium">
                  {t(`rows.${row}`)}
                </th>
                <td className="px-5 py-3 text-center">{cell(FREE[row])}</td>
                <td className="px-5 py-3 text-center">{cell(true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Alert tone="info" className="mx-auto mt-8 max-w-4xl" title={t('safetyTitle')}>
        {t('safetyBody')}
      </Alert>
      <p className="mx-auto mt-4 max-w-4xl text-sm text-muted-foreground">{t('storeNote')}</p>
    </Container>
  );
}
