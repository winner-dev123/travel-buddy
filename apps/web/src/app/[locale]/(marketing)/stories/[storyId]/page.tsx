import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { getFormatter, getTranslations, setRequestLocale } from 'next-intl/server';
import { Flag, Heart, MapPin, MessageCircle } from 'lucide-react';
import { isApiError } from '@travelbuddy/api-client';
import type { PublicPost } from '@travelbuddy/domain-types';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Avatar, Badge, Button, Container } from '@travelbuddy/ui';
import { DestinationArt } from '@/components/destination-art';
import { JsonLd } from '@/components/json-ld';
import { StoryCard } from '@/components/story-card';
import { Link } from '@/i18n/navigation';
import { absoluteUrl, destinationHref, storyHref } from '@/lib/paths';
import { publicPageMetadata } from '@/lib/seo';
import { excerpt, storyTitle } from '@/lib/stories';
import { env } from '@/server/env';
import { publicApi } from '@/server/platform';

/** Short window so that stories made private or removed disappear quickly (see /stories). */
export const revalidate = 60;

type Params = { locale: LocaleCode; storyId: string };

/** No build-time list: each public story renders on first request, then is cached for 60 s (ISR). */
export function generateStaticParams() {
  return [];
}

async function loadStory(locale: string, id: string): Promise<PublicPost | null> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) return null;
  const api = await publicApi(locale);
  try {
    // The public endpoint only ever returns posts the author made public and that passed moderation.
    return await api.publicPosts.get(id, { revalidate: 60, tags: ['stories', `story:${id}`] });
  } catch (error) {
    if (isApiError(error) && error.status === 404) return null;
    throw error;
  }
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { locale, storyId } = await params;
  const story = await loadStory(locale, storyId);
  if (!story) return { robots: { index: false } };
  const t = await getTranslations({ locale, namespace: 'stories.meta' });
  const metadata = publicPageMetadata({
    siteUrl: env().siteUrl,
    locale,
    path: storyHref(story.id),
    title: t('storyTitle', { title: storyTitle(story.body), author: story.author.display_name }),
    description: excerpt(story.body),
    type: 'article',
  });
  // PROF-008: a public story is indexable only when its author opted into search-engine indexing.
  // Absent or false → noindex (and it is left out of the sitemap).
  return story.indexable === true ? metadata : { ...metadata, robots: { index: false, follow: true } };
}

export default async function StoryPage({ params }: { params: Promise<Params> }) {
  const { locale, storyId } = await params;
  setRequestLocale(locale);
  const story = await loadStory(locale, storyId);
  if (!story) notFound();
  const [t, format] = await Promise.all([getTranslations('stories'), getFormatter()]);
  const api = await publicApi(locale);
  const related = story.primary_destination
    ? ((await api.publicPosts.list({ destination_id: story.primary_destination.id, limit: 4 }, { revalidate: 60, tags: ['stories'] }).catch(() => null))?.data ?? []).filter((s) => s.id !== story.id).slice(0, 3)
    : [];
  const siteUrl = env().siteUrl;
  const title = storyTitle(story.body);

  return (
    <>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'SocialMediaPosting',
          headline: title,
          articleBody: story.body,
          inLanguage: story.language,
          datePublished: story.published_at,
          ...(story.edited_at ? { dateModified: story.edited_at } : {}),
          url: absoluteUrl(siteUrl, locale, storyHref(story.id)),
          author: { '@type': 'Person', name: story.author.display_name },
          ...(story.primary_destination ? { contentLocation: { '@type': 'Place', name: story.primary_destination.name } } : {}),
          interactionStatistic: [
            { '@type': 'InteractionCounter', interactionType: 'https://schema.org/LikeAction', userInteractionCount: story.counts.reactions },
            { '@type': 'InteractionCounter', interactionType: 'https://schema.org/CommentAction', userInteractionCount: story.counts.comments },
          ],
        }}
      />
      <Container className="max-w-3xl py-12">
        <article className="flex flex-col gap-6">
          <div className="aspect-[16/9] overflow-hidden rounded-card" aria-hidden="true">
            <DestinationArt seed={story.id} categories={story.tags} />
          </div>
          <header className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              {story.primary_destination ? (
                <Link href={destinationHref(story.primary_destination.path.split('/').slice(0, 2).join('/'))}>
                  <Badge tone="primary">
                    <MapPin aria-hidden="true" />
                    {story.primary_destination.name}
                  </Badge>
                </Link>
              ) : null}
              {story.place ? <Badge tone="outline">{story.place.name}</Badge> : null}
            </div>
            <h1 className="font-display text-headline font-semibold" lang={story.language}>
              {title}
            </h1>
            <div className="flex items-center gap-3">
              <Avatar name={story.author.display_name} src={story.author.avatar?.url} size={44} />
              <div className="flex flex-col">
                <span className="font-semibold">{story.author.display_name}</span>
                <time dateTime={story.published_at} className="text-sm text-muted-foreground">
                  {format.dateTime(new Date(story.published_at), { dateStyle: 'long' })}
                </time>
              </div>
            </div>
          </header>
          <p className="prose-travel whitespace-pre-line" lang={story.language}>
            {story.body}
          </p>
          {story.tags.length > 0 ? (
            <ul className="flex flex-wrap gap-2" aria-label={t('tags')}>
              {story.tags.map((tag) => (
                <li key={tag}>
                  <Badge tone="neutral">#{tag}</Badge>
                </li>
              ))}
            </ul>
          ) : null}
          <footer className="flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Heart className="size-4" aria-hidden="true" />
                {t('reactionCount', { count: story.counts.reactions })}
              </span>
              <span className="flex items-center gap-1.5">
                <MessageCircle className="size-4" aria-hidden="true" />
                {t('commentCount', { count: story.counts.comments })}
              </span>
            </div>
            <div className="flex gap-2">
              <Button asChild variant="soft" size="sm">
                <Link href={`/login?next=${encodeURIComponent(`/posts/${story.id}`)}`}>{t('joinConversation')}</Link>
              </Button>
              <Button asChild variant="ghost" size="sm">
                <Link href={`/login?next=${encodeURIComponent(`/posts/${story.id}?report=1`)}`}>
                  <Flag aria-hidden="true" />
                  {t('report')}
                </Link>
              </Button>
            </div>
          </footer>
        </article>

        {related.length > 0 ? (
          <section aria-labelledby="related-heading" className="mt-16">
            <h2 id="related-heading" className="font-display text-2xl font-semibold">
              {t('related', { name: story.primary_destination?.name ?? '' })}
            </h2>
            <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {related.map((s) => (
                <StoryCard key={s.id} story={s} />
              ))}
            </div>
          </section>
        ) : null}
      </Container>
    </>
  );
}
