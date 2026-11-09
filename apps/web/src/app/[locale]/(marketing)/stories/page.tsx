import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Container } from '@travelbuddy/ui';
import { StoryCard } from '@/components/story-card';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';
import { publicApi } from '@/server/platform';

/**
 * Short revalidation: a story whose author switches it away from public must disappear quickly
 * (docs/web/05 open question 1 — replaced by on-demand revalidation once the platform calls it).
 */
export const revalidate = 60;

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'stories.meta' });
  return publicPageMetadata({ siteUrl: env().siteUrl, locale, path: '/stories', title: t('title'), description: t('description') });
}

export default async function StoriesPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations('stories');
  const api = await publicApi(locale);
  const page = await api.publicPosts.list({ limit: 24 }, { revalidate: 60, tags: ['stories'] }).catch(() => null);
  const stories = page?.data ?? [];

  return (
    <>
      <section className="border-b border-border bg-surface-muted/50">
        <Container className="flex flex-col gap-4 py-14">
          <span className="eyebrow">{t('eyebrow')}</span>
          <h1 className="font-display text-headline font-semibold">{t('title')}</h1>
          <p className="max-w-2xl text-lg text-muted-foreground">{t('subtitle')}</p>
        </Container>
      </section>
      <Container className="py-14">
        {stories.length === 0 ? (
          <p className="text-muted-foreground">{page ? t('empty') : t('unavailable')}</p>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {stories.map((s) => (
              <StoryCard key={s.id} story={s} />
            ))}
          </div>
        )}
        <p className="mt-10 text-sm text-muted-foreground">{t('publicOnlyNote')}</p>
      </Container>
    </>
  );
}
