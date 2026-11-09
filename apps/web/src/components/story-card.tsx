import { getFormatter, getTranslations } from 'next-intl/server';
import { Heart, MapPin, MessageCircle } from 'lucide-react';
import type { PublicPost } from '@travelbuddy/domain-types';
import { Avatar, Badge } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { storyHref } from '@/lib/paths';
import { storyTitle } from '@/lib/stories';
import { DestinationArt } from './destination-art';

/** Card for a PUBLIC story. Only ever rendered with `PublicPost` data (brief §6). */
export async function StoryCard({ story }: { story: PublicPost }) {
  const [t, format] = await Promise.all([getTranslations('stories'), getFormatter()]);
  const title = storyTitle(story.body);
  return (
    <article className="group relative flex flex-col overflow-hidden rounded-card border border-border bg-surface shadow-card">
      <Link href={storyHref(story.id)} className="relative block aspect-[16/10] overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring" tabIndex={-1} aria-hidden="true">
        <DestinationArt seed={story.id} categories={story.tags} />
        {story.primary_destination ? (
          <Badge tone="inverse" className="absolute start-3 top-3">
            <MapPin aria-hidden="true" />
            {story.primary_destination.name}
          </Badge>
        ) : null}
      </Link>
      <div className="flex flex-1 flex-col gap-3 p-5">
        <h3 className="font-display text-lg leading-snug font-semibold" lang={story.language}>
          <Link href={storyHref(story.id)} className="after:absolute after:inset-0 hover:underline focus-visible:outline-none">
            {title}
          </Link>
        </h3>
        <p className="line-clamp-3 text-sm text-muted-foreground" lang={story.language}>
          {story.body}
        </p>
        <div className="mt-auto flex items-center justify-between gap-3 pt-2 text-sm">
          <span className="flex min-w-0 items-center gap-2">
            <Avatar name={story.author.display_name} src={story.author.avatar?.url} size={28} />
            <span className="truncate font-semibold">{story.author.display_name}</span>
          </span>
          <span className="flex shrink-0 items-center gap-3 text-muted-foreground">
            <span className="flex items-center gap-1" aria-label={t('reactionCount', { count: story.counts.reactions })}>
              <Heart className="size-4" aria-hidden="true" />
              {format.number(story.counts.reactions, { notation: 'compact' })}
            </span>
            <span className="flex items-center gap-1" aria-label={t('commentCount', { count: story.counts.comments })}>
              <MessageCircle className="size-4" aria-hidden="true" />
              {story.counts.comments}
            </span>
          </span>
        </div>
        <time dateTime={story.published_at} className="text-xs text-muted-foreground">
          {format.dateTime(new Date(story.published_at), { dateStyle: 'medium' })}
        </time>
      </div>
    </article>
  );
}
