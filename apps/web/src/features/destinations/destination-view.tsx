import { getFormatter, getTranslations } from 'next-intl/server';
import { ChevronRight, Clock, Headphones, Languages, Sparkles } from 'lucide-react';
import type { Destination, DestinationSummary, Guide, PublicPost } from '@travelbuddy/domain-types';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Badge, Button, Card, Container } from '@travelbuddy/ui';
import { DestinationCard } from '@/components/destination-card';
import { JsonLd } from '@/components/json-ld';
import { Markdown } from '@/components/markdown';
import { MediaImage } from '@/components/media-image';
import { StoryCard } from '@/components/story-card';
import { Link } from '@/i18n/navigation';
import { absoluteUrl, destinationHref } from '@/lib/paths';
import { LocationMap } from './location-map';

export async function DestinationView({
  locale,
  siteUrl,
  destination,
  guide,
  subDestinations,
  stories,
}: {
  locale: LocaleCode;
  siteUrl: string;
  destination: Destination;
  guide: Guide | null;
  subDestinations: DestinationSummary[];
  stories: PublicPost[];
}) {
  const [t, tn, format] = await Promise.all([getTranslations('destination'), getTranslations('shell'), getFormatter()]);
  const path = destinationHref(destination.path);
  const url = absoluteUrl(siteUrl, locale, path);
  const prose = guide?.sections.filter((s) => (s.kind ?? 'prose') === 'prose') ?? [];
  const faqs = guide?.sections.filter((s) => s.kind === 'faq').flatMap((s) => s.faq_items ?? []) ?? [];
  const guideLanguageDiffers = guide ? !locale.toLowerCase().startsWith(guide.locale.toLowerCase().split('-')[0] ?? '') : false;
  const crumbs = [
    { name: tn('home'), href: '/' },
    { name: t('breadcrumbDestinations'), href: '/destinations' },
    ...destination.ancestors.map((a) => ({ name: a.name, href: destinationHref(a.path) })),
    { name: destination.name, href: path },
  ];
  const isCountry = destination.kind === 'country';
  const description = destination.tagline ?? guide?.summary ?? '';

  const structured: Record<string, unknown>[] = [
    {
      '@context': 'https://schema.org',
      '@type': isCountry ? 'Country' : 'TouristDestination',
      name: destination.name,
      description,
      url,
      geo: { '@type': 'GeoCoordinates', latitude: destination.centroid.lat, longitude: destination.centroid.lng },
      ...(destination.ancestors[0] && !isCountry ? { containedInPlace: { '@type': 'Country', name: destination.ancestors[0].name } } : {}),
    },
    {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: crumbs.map((c, i) => ({ '@type': 'ListItem', position: i + 1, name: c.name, item: absoluteUrl(siteUrl, locale, c.href) })),
    },
  ];
  if (faqs.length > 0) {
    structured.push({
      '@context': 'https://schema.org',
      '@type': 'FAQPage',
      mainEntity: faqs.map((f) => ({ '@type': 'Question', name: f.question, acceptedAnswer: { '@type': 'Answer', text: f.answer_markdown } })),
    });
  }

  return (
    <>
      <JsonLd data={structured} />

      {/* Hero */}
      <section className="relative isolate overflow-hidden">
        <MediaImage
          media={destination.cover}
          seed={destination.id}
          sizes="100vw"
          priority
          className="absolute inset-0 -z-10"
        />
        <div className="absolute inset-0 -z-10 bg-gradient-to-t from-black/80 via-black/35 to-black/10" aria-hidden="true" />
        <Container className="flex min-h-[26rem] flex-col justify-end gap-4 py-10 text-white sm:min-h-[32rem]">
          <nav aria-label={t('breadcrumb')}>
            <ol className="flex flex-wrap items-center gap-1 text-sm text-white/85">
              {crumbs.map((c, i) => (
                <li key={c.href} className="flex items-center gap-1">
                  {i > 0 ? <ChevronRight className="size-3.5 rtl:rotate-180" aria-hidden="true" /> : null}
                  {i === crumbs.length - 1 ? (
                    <span aria-current="page" className="font-semibold text-white">
                      {c.name}
                    </span>
                  ) : (
                    <Link href={c.href} className="hover:underline">
                      {c.name}
                    </Link>
                  )}
                </li>
              ))}
            </ol>
          </nav>
          {destination.country_name ? <p className="text-lg font-medium text-white/90">{destination.country_name}</p> : null}
          <h1 className="font-display text-display font-semibold">{destination.name}</h1>
          {destination.tagline ? <p className="max-w-2xl text-lg text-white/90">{destination.tagline}</p> : null}
          <div className="mt-2 flex flex-wrap gap-3">
            <Button asChild variant="accent" size="lg">
              <Link href={`/register?next=${encodeURIComponent(`/assistant?destination=${destination.id}`)}`}>
                <Sparkles aria-hidden="true" />
                {t('planCta', { name: destination.name })}
              </Link>
            </Button>
            <Button asChild variant="inverse" size="lg">
              <Link href="/register">{t('joinCta')}</Link>
            </Button>
          </div>
        </Container>
      </section>

      <Container className="grid gap-12 py-14 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-14">
          {/* Overview from the free editorial guide */}
          <section aria-labelledby="overview-heading" className="flex flex-col gap-4">
            <h2 id="overview-heading" className="font-display text-3xl font-semibold">
              {t('overview')}
            </h2>
            {guideLanguageDiffers ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Languages className="size-4" aria-hidden="true" />
                {t('contentLanguageNote')}
              </p>
            ) : null}
            {prose.length > 0 ? (
              <div className="prose-travel flex flex-col gap-6" lang={guide?.locale}>
                {prose.map((s) => (
                  <section key={s.id} aria-label={s.heading}>
                    {s.id !== 'overview' ? <h3 className="mb-2 font-display text-xl font-semibold">{s.heading}</h3> : null}
                    <Markdown source={s.body_markdown} />
                  </section>
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground">{t('noGuide')}</p>
            )}
          </section>

          {subDestinations.length > 0 ? (
            <section aria-labelledby="children-heading">
              <h2 id="children-heading" className="font-display text-3xl font-semibold">
                {isCountry ? t('citiesIn', { name: destination.name }) : t('neighbourhoods')}
              </h2>
              {isCountry ? (
                <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
                  {subDestinations.map((c) => (
                    <DestinationCard key={c.id} destination={c} />
                  ))}
                </div>
              ) : (
                <ul className="mt-5 flex flex-wrap gap-2">
                  {subDestinations.map((c) => (
                    <li key={c.id}>
                      <Badge tone="primary" className="px-4 py-1.5 text-sm">
                        {c.name}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : null}

          <section aria-labelledby="stories-heading">
            <h2 id="stories-heading" className="font-display text-3xl font-semibold">
              {t('stories', { name: destination.name })}
            </h2>
            {stories.length > 0 ? (
              <div className="mt-6 grid gap-5 md:grid-cols-2">
                {stories.map((s) => (
                  <StoryCard key={s.id} story={s} />
                ))}
              </div>
            ) : (
              <p className="mt-4 text-muted-foreground">{t('noStories')}</p>
            )}
          </section>

          {faqs.length > 0 ? (
            <section aria-labelledby="faq-heading">
              <h2 id="faq-heading" className="font-display text-3xl font-semibold">
                {t('faq')}
              </h2>
              <div className="mt-5 divide-y divide-border rounded-card border border-border bg-surface">
                {faqs.map((f) => (
                  <details key={f.question} className="group px-5 py-4">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold [&::-webkit-details-marker]:hidden">
                      <span lang={guide?.locale}>{f.question}</span>
                      <ChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90" aria-hidden="true" />
                    </summary>
                    <Markdown source={f.answer_markdown} className="mt-3 text-muted-foreground" />
                  </details>
                ))}
              </div>
            </section>
          ) : null}

          {guide ? (
            <p className="text-xs text-muted-foreground">
              {t('contentFooter', { license: guide.content_license, date: format.dateTime(new Date(guide.updated_at), { dateStyle: 'long' }) })}{' '}
              {t('noLiveInfo')}
            </p>
          ) : null}
        </div>

        <aside className="flex flex-col gap-6" aria-label={t('sidebar')}>
          <LocationMap center={destination.centroid} label={destination.name} zoom={isCountry ? 4 : 10} />
          <Card className="flex flex-col gap-3 p-5">
            <h2 className="font-display text-lg font-semibold">{t('facts')}</h2>
            <p className="flex items-center gap-2 text-sm">
              <Clock className="size-4 text-primary" aria-hidden="true" />
              <span>
                {t('timeZone')}: <span className="font-semibold">{destination.time_zone}</span>
              </span>
            </p>
          </Card>
          <Card className="flex flex-col gap-3 bg-primary-soft p-5">
            <Sparkles className="size-6 text-primary" aria-hidden="true" />
            <h2 className="font-display text-lg font-semibold">{t('itineraryTitle')}</h2>
            <p className="text-sm text-muted-foreground">{t('itineraryBody', { name: destination.name })}</p>
            <Button asChild variant="primary">
              <Link href={`/register?next=${encodeURIComponent(`/assistant?destination=${destination.id}`)}`}>{t('planCta', { name: destination.name })}</Link>
            </Button>
          </Card>
          <Card className="flex flex-col gap-2 p-5">
            <Headphones className="size-6 text-primary" aria-hidden="true" />
            <h2 className="font-display text-lg font-semibold">{t('audioTitle')}</h2>
            <p className="text-sm text-muted-foreground">{t('audioBody')}</p>
          </Card>
        </aside>
      </Container>
    </>
  );
}
