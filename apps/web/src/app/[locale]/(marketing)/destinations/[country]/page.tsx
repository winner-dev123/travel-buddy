import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { DestinationView } from '@/features/destinations/destination-view';
import { getChildren, getDestination, getDestinationStories, getFreeGuide } from '@/features/destinations/data';
import { destinationHref } from '@/lib/paths';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';

export const revalidate = 3600;

type Params = { locale: LocaleCode; country: string };

/** Pre-render countries; unknown slugs render on demand (404 if missing) and are then cached. */
export async function generateStaticParams({ params }: { params: { locale: string } }) {
  try {
    const api = await (await import('@/server/platform')).publicApi(params.locale);
    const page = await api.destinations.list({ kind: ['country'], sort: 'slug', limit: 100 });
    return page.data.map((d) => ({ country: d.slug }));
  } catch {
    return [];
  }
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { locale, country } = await params;
  const destination = await getDestination(locale, country);
  if (!destination || destination.kind !== 'country') return {};
  const t = await getTranslations({ locale, namespace: 'destination.meta' });
  return publicPageMetadata({
    siteUrl: env().siteUrl,
    locale,
    path: destinationHref(destination.path),
    title: t('countryTitle', { name: destination.name }),
    description: destination.tagline ?? t('description', { name: destination.name }),
  });
}

export default async function CountryPage({ params }: { params: Promise<Params> }) {
  const { locale, country } = await params;
  setRequestLocale(locale);
  const destination = await getDestination(locale, country);
  if (!destination || destination.kind !== 'country') notFound();
  const [guide, children, stories] = await Promise.all([
    destination.has_guides ? getFreeGuide(locale, destination.id) : Promise.resolve(null),
    getChildren(locale, destination.id),
    getDestinationStories(locale, destination.id),
  ]);
  return (
    <DestinationView
      locale={locale}
      siteUrl={env().siteUrl}
      destination={destination}
      guide={guide}
      subDestinations={children.filter((c) => c.kind === 'city')}
      stories={stories}
    />
  );
}
