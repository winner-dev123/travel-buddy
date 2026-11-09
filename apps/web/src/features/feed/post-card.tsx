'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useFormatter, useLocale, useNow, useTranslations } from 'next-intl';
import { Bookmark, Flag, Heart, MapPin, MessageCircle, MoreHorizontal, Share2, ShieldBan } from 'lucide-react';
import type { Post, PostCounts, ReactionType } from '@travelbuddy/domain-types';
import { Avatar, Badge, cn } from '@travelbuddy/ui';
import { DestinationArt } from '@/components/destination-art';
import { Link } from '@/i18n/navigation';
import { browserApi } from '@/lib/api-browser';
import { localizedPath } from '@/lib/paths';
import { qk } from '@/lib/query-keys';
import { ReportDialog } from './report-dialog';

/**
 * Feed post card. Reactions and bookmarks are optimistic (idempotent endpoints) with rollback on
 * error. Share is offered only for publicly listed posts (public + approved), so other content never gets a
 * shareable link; each share is recorded through the platform's share endpoint.
 */
export function PostCard({ post, onHidden }: { post: Post; onHidden?: (postId: string) => void }) {
  const t = useTranslations('post');
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [reaction, setReaction] = useState<ReactionType | null>(post.viewer.reaction);
  const [counts, setCounts] = useState<PostCounts>(post.counts);
  const [bookmarked, setBookmarked] = useState(post.viewer.bookmarked);
  const [reportOpen, setReportOpen] = useState(false);
  const [shared, setShared] = useState(false);

  const react = useMutation({
    mutationFn: async (next: ReactionType | null) => (next ? browserApi().posts.react(post.id, next) : browserApi().posts.unreact(post.id)),
    onMutate: (next) => {
      const previous = { reaction, counts };
      const delta = (next ? 1 : 0) - (reaction ? 1 : 0);
      setReaction(next);
      setCounts((c) => ({ ...c, reactions: Math.max(0, c.reactions + delta) }));
      return previous;
    },
    onError: (_e, _v, previous) => {
      if (previous) {
        setReaction(previous.reaction);
        setCounts(previous.counts);
      }
    },
    onSuccess: (result) => {
      if (result && 'counts' in result) setCounts(result.counts);
    },
  });

  const bookmark = useMutation({
    mutationFn: async (next: boolean) => (next ? browserApi().posts.bookmark(post.id) : browserApi().posts.unbookmark(post.id)),
    onMutate: (next) => {
      setBookmarked(next);
      return !next;
    },
    onError: (_e, _v, previous) => setBookmarked(Boolean(previous)),
  });

  const block = useMutation({
    mutationFn: () => browserApi().users.block(post.author.id),
    onSuccess: () => {
      onHidden?.(post.id);
      void queryClient.invalidateQueries({ queryKey: qk.feedAll() });
      void queryClient.invalidateQueries({ queryKey: qk.blocks() });
    },
  });

  const share = async () => {
    const url = `${window.location.origin}${localizedPath(locale, `/stories/${post.id}`)}`;
    // Records the share (contract: increments the share count). Not awaited before the share sheet, which
    // must open within the click's user activation; a failure here never blocks sharing.
    void browserApi().posts.share(post.id).catch(() => undefined);
    try {
      if (navigator.share) await navigator.share({ url });
      else {
        await navigator.clipboard.writeText(url);
        setShared(true);
        setTimeout(() => setShared(false), 2500);
      }
    } catch {
      // user cancelled the share sheet
    }
  };

  // Only publicly listed posts have a working guest link: public and approved. `moderation_state` is sent
  // only to the author; for everyone else it is absent and the post is approved by definition.
  const shareable = post.visibility === 'public' && (post.moderation_state ?? 'approved') === 'approved';
  const published = new Date(post.published_at);
  const destination = post.primary_destination;

  return (
    <article className="cv-auto overflow-hidden rounded-card border border-border bg-surface shadow-card" aria-labelledby={`post-${post.id}-author`}>
      <header className="flex items-center gap-3 px-4 pt-4">
        <Avatar name={post.author.display_name} src={post.author.avatar?.url} size={42} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span id={`post-${post.id}-author`} className="truncate font-semibold">
            {post.author.display_name}
          </span>
          <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
            {destination ? (
              <span className="flex items-center gap-1">
                <MapPin className="size-3" aria-hidden="true" />
                {post.place ? `${post.place.name} · ` : ''}
                {destination.name}
              </span>
            ) : null}
            <span aria-hidden="true">·</span>
            <time dateTime={post.published_at} title={format.dateTime(published, { dateStyle: 'medium', timeStyle: 'short' })}>
              {format.relativeTime(published, now)}
            </time>
            {post.visibility !== 'public' ? <Badge tone="outline" className="ms-1 py-0">{t(`visibility.${post.visibility}`)}</Badge> : null}
          </span>
        </div>
        <details className="relative">
          <summary className="flex size-9 cursor-pointer list-none items-center justify-center rounded-full text-muted-foreground hover:bg-surface-muted [&::-webkit-details-marker]:hidden" aria-label={t('moreActions')}>
            <MoreHorizontal className="size-5" aria-hidden="true" />
          </summary>
          <div className="absolute end-0 top-10 z-20 flex w-52 flex-col rounded-2xl border border-border bg-surface p-1.5 shadow-lift">
            {!post.viewer.is_author ? (
              <>
                <button type="button" onClick={() => setReportOpen(true)} className="flex items-center gap-2 rounded-xl px-3 py-2 text-start text-sm hover:bg-surface-muted">
                  <Flag className="size-4" aria-hidden="true" />
                  {t('report')}
                </button>
                <button type="button" onClick={() => block.mutate()} className="flex items-center gap-2 rounded-xl px-3 py-2 text-start text-sm text-danger hover:bg-surface-muted">
                  <ShieldBan className="size-4" aria-hidden="true" />
                  {t('block', { name: post.author.display_name })}
                </button>
              </>
            ) : (
              <span className="px-3 py-2 text-xs text-muted-foreground">{t('yourPost')}</span>
            )}
          </div>
        </details>
      </header>

      <div className="flex flex-col gap-3 px-4 py-3">
        <p className="whitespace-pre-line text-[0.95rem] leading-relaxed" lang={post.language}>
          {post.body}
        </p>
        {post.tags.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label={t('tags')}>
            {post.tags.map((tag) => (
              <li key={tag}>
                <Badge tone="secondary">#{tag}</Badge>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {post.media.length === 0 && destination ? (
        <div className="relative mx-4 mb-3 aspect-[16/7] overflow-hidden rounded-2xl" aria-hidden="true">
          <DestinationArt seed={post.id} categories={post.tags} />
        </div>
      ) : null}

      <footer className="flex items-center gap-1 border-t border-border px-2 py-1.5">
        <button
          type="button"
          aria-pressed={reaction !== null}
          aria-label={reaction ? t('unlike') : t('like')}
          onClick={() => react.mutate(reaction ? null : 'like')}
          className={cn('flex items-center gap-1.5 rounded-pill px-3 py-2 text-sm font-semibold transition-colors hover:bg-surface-muted', reaction ? 'text-accent' : 'text-muted-foreground')}
        >
          <Heart className={cn('size-5', reaction && 'fill-current')} aria-hidden="true" />
          {format.number(counts.reactions, { notation: 'compact' })}
        </button>
        <Link href={`/posts/${post.id}`} className="flex items-center gap-1.5 rounded-pill px-3 py-2 text-sm font-semibold text-muted-foreground hover:bg-surface-muted" aria-label={t('comments', { count: counts.comments })}>
          <MessageCircle className="size-5" aria-hidden="true" />
          {counts.comments}
        </Link>
        {shareable ? (
          <button type="button" onClick={share} className="flex items-center gap-1.5 rounded-pill px-3 py-2 text-sm font-semibold text-muted-foreground hover:bg-surface-muted" aria-label={t('share')}>
            <Share2 className="size-5" aria-hidden="true" />
            <span className="text-xs" role="status">
              {shared ? t('copied') : ''}
            </span>
          </button>
        ) : null}
        <button
          type="button"
          aria-pressed={bookmarked}
          aria-label={bookmarked ? t('unsave') : t('save')}
          onClick={() => bookmark.mutate(!bookmarked)}
          className={cn('ms-auto flex items-center rounded-pill px-3 py-2 hover:bg-surface-muted', bookmarked ? 'text-primary' : 'text-muted-foreground')}
        >
          <Bookmark className={cn('size-5', bookmarked && 'fill-current')} aria-hidden="true" />
        </button>
      </footer>

      <ReportDialog open={reportOpen} onOpenChange={setReportOpen} targetType="post" targetId={post.id} onBlocked={() => onHidden?.(post.id)} />
    </article>
  );
}
