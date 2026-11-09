import type { Metadata } from 'next';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import {
  ArrowRight,
  BadgeCheck,
  Compass,
  EyeOff,
  Headphones,
  MapPinned,
  Puzzle,
  ShieldCheck,
  Sparkles,
  Users,
  UsersRound,
} from 'lucide-react';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Badge, Button, Card, Container } from '@travelbuddy/ui';
import { DestinationArt } from '@/components/destination-art';
import { DestinationCard } from '@/components/destination-card';
import { DestinationSearchNav } from '@/components/destination-search-nav';
import { JsonLd } from '@/components/json-ld';
import { StoreButtons } from '@/components/store-buttons';
import { StoryCard } from '@/components/story-card';
import { Link } from '@/i18n/navigation';
import { publicPageMetadata } from '@/lib/seo';
import { env } from '@/server/env';
import { publicApi } from '@/server/platform';

export const revalidate = 600;

export async function generateMetadata({ params }: { params: Promise<{ locale: LocaleCode }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'home.meta' });
  return publicPageMetadata({ siteUrl: env().siteUrl, locale, path: '/', title: t('title'), description: t('description') });
}

async function loadHome(locale: string) {
  const api = await publicApi(locale);
  const [featured, stories] = await Promise.all([
    api.destinations.featured({ limit: 8 }, { revalidate: 3600, tags: ['destinations'] }).catch(() => null),
    api.publicPosts.list({ limit: 3 }, { revalidate: 60, tags: ['stories'] }).catch(() => null),
  ]);
  return { featured: featured?.data ?? [], stories: stories?.data ?? [] };
}

export default async function HomePage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, data] = await Promise.all([getTranslations('home'), loadHome(locale)]);
  const siteUrl = env().siteUrl;

  return (
    <>
      <JsonLd
        data={[
          { '@context': 'https://schema.org', '@type': 'Organization', name: 'Travel Buddy', url: siteUrl, logo: `${siteUrl}/icon.svg` },
          { '@context': 'https://schema.org', '@type': 'WebSite', name: 'Travel Buddy', url: siteUrl, inLanguage: locale },
        ]}
      />

      {/* 1–2. Hero + destination search */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top_right,color-mix(in_oklab,var(--tb-secondary)_22%,transparent),transparent_55%),radial-gradient(ellipse_at_bottom_left,color-mix(in_oklab,var(--tb-accent)_16%,transparent),transparent_50%)]" aria-hidden="true" />
        <Container className="grid items-center gap-12 py-16 lg:grid-cols-[1.1fr_0.9fr] lg:py-24">
          <div className="flex flex-col gap-7">
            <span className="eyebrow">{t('hero.eyebrow')}</span>
            <h1 className="font-display text-display font-semibold tracking-tight">
              {t('hero.titleStart')} <span className="text-primary">{t('hero.titleAccent')}</span>
            </h1>
            <p className="max-w-xl text-lg text-muted-foreground">{t('hero.subtitle')}</p>
            <DestinationSearchNav className="max-w-xl" />
            <div className="flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg">
                <Link href="/destinations">
                  <Compass aria-hidden="true" />
                  {t('hero.ctaExplore')}
                </Link>
              </Button>
              <Button asChild variant="accent" size="lg">
                <Link href="/register?next=/assistant">
                  <Sparkles aria-hidden="true" />
                  {t('hero.ctaPlan')}
                </Link>
              </Button>
              <Button asChild variant="secondary" size="lg">
                <Link href="/register">
                  <Users aria-hidden="true" />
                  {t('hero.ctaJoin')}
                </Link>
              </Button>
            </div>
          </div>
          <HeroCollage labels={{ nearby: t('hero.chipNearby'), itinerary: t('hero.chipItinerary'), stories: t('hero.chipStories') }} />
        </Container>
      </section>

      {/* 3. Discovery introduction */}
      <section aria-labelledby="discover-heading" className="py-16">
        <Container>
          <SectionHeading id="discover-heading" eyebrow={t('discover.eyebrow')} title={t('discover.title')} subtitle={t('discover.subtitle')} />
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {(['local', 'plan', 'together'] as const).map((key, i) => {
              const Icon = [MapPinned, Sparkles, UsersRound][i] ?? Compass;
              return (
                <Card key={key} className="flex flex-col gap-3 p-6">
                  <span className="flex size-11 items-center justify-center rounded-2xl bg-primary-soft text-primary">
                    <Icon className="size-5" aria-hidden="true" />
                  </span>
                  <h3 className="font-display text-xl font-semibold">{t(`discover.${key}.title`)}</h3>
                  <p className="text-sm text-muted-foreground">{t(`discover.${key}.body`)}</p>
                </Card>
              );
            })}
          </div>
        </Container>
      </section>

      {/* 4. Popular destinations */}
      <section aria-labelledby="popular-heading" className="py-16">
        <Container>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <SectionHeading id="popular-heading" eyebrow={t('popular.eyebrow')} title={t('popular.title')} />
            <Button asChild variant="secondary">
              <Link href="/destinations">
                {t('popular.cta')} <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
              </Link>
            </Button>
          </div>
          {data.featured.length > 0 ? (
            <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {data.featured.slice(0, 8).map((d, i) => (
                <DestinationCard key={d.id} destination={d} priority={i < 2} />
              ))}
            </div>
          ) : (
            <p className="mt-8 text-muted-foreground">{t('popular.unavailable')}</p>
          )}
        </Container>
      </section>

      {/* 5. Featured stories */}
      {data.stories.length > 0 ? (
        <section aria-labelledby="stories-heading" className="bg-surface-muted/60 py-16">
          <Container>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <SectionHeading id="stories-heading" eyebrow={t('stories.eyebrow')} title={t('stories.title')} subtitle={t('stories.subtitle')} />
              <Button asChild variant="secondary">
                <Link href="/stories">
                  {t('stories.cta')} <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
                </Link>
              </Button>
            </div>
            <div className="mt-10 grid gap-5 md:grid-cols-3">
              {data.stories.map((s) => (
                <StoryCard key={s.id} story={s} />
              ))}
            </div>
          </Container>
        </section>
      ) : null}

      {/* 6. AI planner illustration (marketing visual, clearly labelled — not a simulation) */}
      <section aria-labelledby="ai-heading" className="py-20">
        <Container className="grid items-center gap-12 lg:grid-cols-2">
          <div className="flex flex-col gap-5">
            <SectionHeading id="ai-heading" eyebrow={t('ai.eyebrow')} title={t('ai.title')} subtitle={t('ai.subtitle')} />
            <ul className="flex flex-col gap-3 text-sm">
              {(['grounded', 'editable', 'honest'] as const).map((k) => (
                <li key={k} className="flex gap-3">
                  <BadgeCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
                  <span>{t(`ai.points.${k}`)}</span>
                </li>
              ))}
            </ul>
            <Button asChild variant="accent" size="lg" className="w-fit">
              <Link href="/register?next=/assistant">
                <Sparkles aria-hidden="true" />
                {t('hero.ctaPlan')}
              </Link>
            </Button>
          </div>
          <Card className="relative overflow-hidden p-0">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <p className="text-sm font-semibold">{t('ai.sample.title')}</p>
              <Badge tone="outline">{t('ai.sample.badge')}</Badge>
            </div>
            <ol className="flex flex-col gap-4 p-5">
              {(['d1', 'd2', 'd3'] as const).map((d, i) => (
                <li key={d} className="flex gap-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">{i + 1}</span>
                  <div>
                    <p className="font-semibold">{t(`ai.sample.${d}.title`)}</p>
                    <p className="text-sm text-muted-foreground">{t(`ai.sample.${d}.body`)}</p>
                  </div>
                </li>
              ))}
            </ol>
            <p className="border-t border-border px-5 py-3 text-xs text-muted-foreground">{t('ai.sample.disclaimer')}</p>
          </Card>
        </Container>
      </section>

      {/* 7–9. Companions, groups & challenges, audio guides */}
      <section aria-labelledby="community-heading" className="bg-[#0f2a2f] py-20 text-white">
        <Container>
          <div className="max-w-2xl">
            <span className="eyebrow text-secondary">{t('community.eyebrow')}</span>
            <h2 id="community-heading" className="mt-3 font-display text-headline font-semibold">
              {t('community.title')}
            </h2>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            <FeatureDark icon={<ShieldCheck />} title={t('community.companions.title')} body={t('community.companions.body')}>
              <ul className="mt-4 flex flex-col gap-2 text-sm text-white/80">
                <li className="flex items-center gap-2">
                  <EyeOff className="size-4 text-secondary" aria-hidden="true" />
                  {t('community.companions.p1')}
                </li>
                <li className="flex items-center gap-2">
                  <MapPinned className="size-4 text-secondary" aria-hidden="true" />
                  {t('community.companions.p2')}
                </li>
              </ul>
            </FeatureDark>
            <FeatureDark icon={<Puzzle />} title={t('community.groups.title')} body={t('community.groups.body')} />
            <FeatureDark icon={<Headphones />} title={t('community.audio.title')} body={t('community.audio.body')} />
          </div>
        </Container>
      </section>

      {/* 10. Premium benefits */}
      <section aria-labelledby="premium-heading" className="py-20">
        <Container className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <SectionHeading id="premium-heading" eyebrow={t('premium.eyebrow')} title={t('premium.title')} subtitle={t('premium.subtitle')} />
          <Card className="grid gap-4 p-6 sm:grid-cols-2">
            {(['groups', 'ai', 'guides', 'offline'] as const).map((k) => (
              <div key={k} className="flex gap-3">
                <BadgeCheck className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
                <div>
                  <p className="font-semibold">{t(`premium.items.${k}.title`)}</p>
                  <p className="text-sm text-muted-foreground">{t(`premium.items.${k}.body`)}</p>
                </div>
              </div>
            ))}
            <Button asChild variant="primary" className="sm:col-span-2">
              <Link href="/pricing">{t('premium.cta')}</Link>
            </Button>
          </Card>
        </Container>
      </section>

      {/* 11. Apps */}
      <section aria-labelledby="apps-heading" className="pb-8">
        <Container>
          <div className="relative overflow-hidden rounded-[2rem] bg-primary px-6 py-12 text-primary-foreground sm:px-12">
            <div className="absolute -end-16 -top-16 size-64 rounded-full bg-secondary/40 blur-3xl" aria-hidden="true" />
            <div className="relative grid gap-8 md:grid-cols-[1.4fr_1fr] md:items-center">
              <div>
                <h2 id="apps-heading" className="font-display text-headline font-semibold">
                  {t('apps.title')}
                </h2>
                <p className="mt-3 max-w-lg">{t('apps.subtitle')}</p>
              </div>
              <StoreButtons tone="light" />
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}

function SectionHeading({ id, eyebrow, title, subtitle }: { id: string; eyebrow: string; title: string; subtitle?: string }) {
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      <span className="eyebrow">{eyebrow}</span>
      <h2 id={id} className="font-display text-headline font-semibold tracking-tight">
        {title}
      </h2>
      {subtitle ? <p className="text-muted-foreground">{subtitle}</p> : null}
    </div>
  );
}

function FeatureDark({ icon, title, body, children }: { icon: React.ReactNode; title: string; body: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-card border border-white/10 bg-white/5 p-6">
      <span className="flex size-11 items-center justify-center rounded-2xl bg-secondary/20 text-secondary [&_svg]:size-5" aria-hidden="true">
        {icon}
      </span>
      <h3 className="mt-4 font-display text-xl font-semibold">{title}</h3>
      <p className="mt-2 text-sm text-white/80">{body}</p>
      {children}
    </div>
  );
}

function HeroCollage({ labels }: { labels: { nearby: string; itinerary: string; stories: string } }) {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-md" aria-hidden="true">
      <div className="absolute start-0 top-6 h-[62%] w-[58%] -rotate-3 overflow-hidden rounded-card shadow-lift">
        <DestinationArt seed="hero-coast" categories={['beaches']} />
      </div>
      <div className="absolute end-0 top-0 h-[48%] w-[48%] rotate-3 overflow-hidden rounded-card shadow-lift">
        <DestinationArt seed="hero-city" categories={['culture']} />
      </div>
      <div className="absolute end-6 bottom-0 h-[50%] w-[56%] rotate-2 overflow-hidden rounded-card shadow-lift">
        <DestinationArt seed="hero-peaks" categories={['nature']} />
      </div>
      <span className="absolute start-4 bottom-16 rounded-pill bg-surface px-4 py-2 text-sm font-semibold shadow-card">📍 {labels.nearby}</span>
      <span className="absolute end-2 top-[46%] rounded-pill bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground shadow-card">✨ {labels.itinerary}</span>
      <span className="absolute start-[38%] top-0 rounded-pill bg-surface px-4 py-2 text-sm font-semibold shadow-card">💬 {labels.stories}</span>
    </div>
  );
}
