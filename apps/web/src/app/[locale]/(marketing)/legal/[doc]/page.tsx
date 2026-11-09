import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Alert, Container } from '@travelbuddy/ui';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';

const DOCS = ['terms', 'privacy', 'cookies', 'community-guidelines'] as const;
type Doc = (typeof DOCS)[number];
const KEY: Record<Doc, 'terms' | 'privacy' | 'cookies' | 'guidelines'> = {
  terms: 'terms',
  privacy: 'privacy',
  cookies: 'cookies',
  'community-guidelines': 'guidelines',
};

export const dynamicParams = false;

export function generateStaticParams() {
  return DOCS.map((doc) => ({ doc }));
}

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode; doc: string }> }): Promise<Metadata> {
  const { locale, doc } = await params;
  if (!DOCS.includes(doc as Doc)) return {};
  const t = await getTranslations({ locale, namespace: 'legal' });
  const key = KEY[doc as Doc];
  return {
    ...publicPageMetadata({ siteUrl: env().siteUrl, locale, path: `/legal/${doc}`, title: t(`${key}.title`), description: t(`${key}.summary`) }),
    // Draft documents stay out of search results until legal review signs them off.
    robots: { index: false, follow: true },
  };
}

/**
 * Placeholder legal pages. The binding texts are owned by legal counsel and served by the platform
 * CMS (backlog); these pages state the product commitments already made in the architecture docs and
 * are clearly marked as drafts.
 */
export default async function LegalPage({ params }: { params: Promise<{ locale: LocaleCode; doc: string }> }) {
  const { locale, doc } = await params;
  if (!DOCS.includes(doc as Doc)) notFound();
  setRequestLocale(locale);
  const t = await getTranslations('legal');
  const key = KEY[doc as Doc];
  return (
    <Container className="max-w-3xl py-16">
      <h1 className="font-display text-headline font-semibold">{t(`${key}.title`)}</h1>
      <Alert tone="warning" className="mt-6" title={t('draftTitle')}>
        {t('draftBody')}
      </Alert>
      <div className="prose-travel mt-8">
        <p>{t(`${key}.summary`)}</p>
      </div>
    </Container>
  );
}
