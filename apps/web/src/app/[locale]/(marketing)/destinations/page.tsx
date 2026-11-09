import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { CONTINENTS, type DestinationSummary } from '@travelbuddy/domain-types';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Container } from '@travelbuddy/ui';
import { DestinationCard } from '@/components/destination-card';
import { DestinationSearchNav } from '@/components/destination-search-nav';
import { JsonLd } from '@/components/json-ld';
import { Link } from '@/i18n/navigation';
import { absoluteUrl, destinationHref } from '@/lib/paths';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';
import { publicApi } from '@/server/platform';

export const revalidate = 3600;

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'destinations.meta' });
  return publicPageMetadata({ siteUrl: env().siteUrl, locale, path: '/destinations', title: t('title'), description: t('description') });
}

/** Walks the anonymous list endpoint (stable `sort=slug`) up to a safety cap. */
async function listAll(locale: string, kind: 'city' | 'country'): Promise<DestinationSummary[]> {
  const api = await publicApi(locale);
  const out: DestinationSummary[] = [];
  let cursor: string | null | undefined;
  for (let i = 0; i < 20; i++) {
    const page = await api.destinations.list({ kind: [kind], sort: 'slug', limit: 100, cursor }, { revalidate: 3600, tags: ['destinations'] });
    out.push(...page.data);
    if (!page.page.has_more || !page.page.next_cursor) break;
    cursor = page.page.next_cursor;
  }
  return out;
}

export default async function DestinationsPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, tc] = await Promise.all([getTranslations('destinations'), getTranslations('continents')]);
  const [cities, countries] = await Promise.all([
    listAll(locale, 'city').catch(() => [] as DestinationSummary[]),
    listAll(locale, 'country').catch(() => [] as DestinationSummary[]),
  ]);
  const byContinent = CONTINENTS.map((c) => ({ continent: c, cities: cities.filter((d) => d.continent === c) })).filter((g) => g.cities.length > 0);
  const siteUrl = env().siteUrl;

  return (
    <>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'ItemList',
          name: t('meta.title'),
          itemListElement: cities.slice(0, 50).map((d, i) => ({
            '@type': 'ListItem',
            position: i + 1,
            url: absoluteUrl(siteUrl, locale, destinationHref(d.path)),
            name: d.name,
          })),
        }}
      />
      <section className="border-b border-border bg-surface-muted/50">
        <Container className="flex flex-col gap-6 py-14">
          <span className="eyebrow">{t('eyebrow')}</span>
          <h1 className="font-display text-headline font-semibold">{t('title')}</h1>
          <p className="max-w-2xl text-lg text-muted-foreground">{t('subtitle')}</p>
          <DestinationSearchNav className="max-w-xl" />
          {byContinent.length > 0 ? (
            <nav aria-label={t('continentsNav')} className="flex flex-wrap gap-2">
              {byContinent.map((g) => (
                <a key={g.continent} href={`#${g.continent}`} className="rounded-pill border border-border bg-surface px-4 py-2 text-sm font-semibold hover:border-primary">
                  {tc(g.continent)} <span className="text-muted-foreground">· {g.cities.length}</span>
                </a>
              ))}
            </nav>
          ) : null}
        </Container>
      </section>

      <Container className="flex flex-col gap-16 py-14">
        {byContinent.length === 0 ? <p className="text-muted-foreground">{t('unavailable')}</p> : null}
        {byContinent.map((g) => (
          <section key={g.continent} id={g.continent} aria-labelledby={`h-${g.continent}`} className="scroll-mt-24">
            <h2 id={`h-${g.continent}`} className="font-display text-3xl font-semibold">
              {tc(g.continent)}
            </h2>
            <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {g.cities.map((d) => (
                <DestinationCard key={d.id} destination={d} />
              ))}
            </div>
          </section>
        ))}

        {countries.length > 0 ? (
          <section aria-labelledby="countries-heading">
            <h2 id="countries-heading" className="font-display text-3xl font-semibold">
              {t('countries')}
            </h2>
            <ul className="mt-6 flex flex-wrap gap-2">
              {countries.map((c) => (
                <li key={c.id}>
                  <Link href={destinationHref(c.path)} className="inline-flex rounded-pill border border-border bg-surface px-4 py-2 text-sm font-semibold hover:border-primary hover:text-primary">
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </Container>
    </>
  );
}
