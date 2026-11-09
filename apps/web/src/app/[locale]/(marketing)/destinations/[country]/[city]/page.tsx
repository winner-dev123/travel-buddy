import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { DestinationView } from '@/features/destinations/destination-view';
import { getChildren, getDestination, getDestinationStories, getFreeGuide } from '@/features/destinations/data';
import { destinationHref } from '@/lib/paths';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';
import { publicApi } from '@/server/platform';

export const revalidate = 3600;

type Params = { locale: LocaleCode; country: string; city: string };

/** Pre-render the most popular cities; the long tail renders on first request and is cached. */
export async function generateStaticParams({ params }: { params: { locale: string } }) {
  try {
    const api = await publicApi(params.locale);
    const page = await api.destinations.list({ kind: ['city'], sort: 'popularity', limit: 50 });
    return page.data.map((d) => {
      const [country, city] = d.path.split('/');
      return { country: country ?? '', city: city ?? '' };
    });
  } catch {
    return [];
  }
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { locale, country, city } = await params;
  const destination = await getDestination(locale, `${country}/${city}`);
  if (!destination) return {};
  const t = await getTranslations({ locale, namespace: 'destination.meta' });
  return publicPageMetadata({
    siteUrl: env().siteUrl,
    locale,
    path: destinationHref(destination.path),
    title: t('title', { name: destination.name, country: destination.country_name ?? '' }),
    description: destination.tagline ?? t('description', { name: destination.name }),
  });
}

export default async function CityPage({ params }: { params: Promise<Params> }) {
  const { locale, country, city } = await params;
  setRequestLocale(locale);
  const destination = await getDestination(locale, `${country}/${city}`);
  if (!destination || destination.kind === 'country' || destination.path !== `${country}/${city}`) notFound();
  const [guide, children, stories] = await Promise.all([
    destination.has_guides ? getFreeGuide(locale, destination.id) : Promise.resolve(null),
    destination.has_children ? getChildren(locale, destination.id) : Promise.resolve([]),
    getDestinationStories(locale, destination.id),
  ]);
  return <DestinationView locale={locale} siteUrl={env().siteUrl} destination={destination} guide={guide} subDestinations={children} stories={stories} />;
}
