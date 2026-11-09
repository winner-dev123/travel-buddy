'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useFormatter, useNow, useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { isApiError } from '@travelbuddy/api-client';
import { LIMITS } from '@travelbuddy/validation';
import { Alert, Avatar, Button, EmptyState, Skeleton, Textarea } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { browserApi } from '@/lib/api-browser';
import { qk } from '@/lib/query-keys';
import { PostCard } from './post-card';
import { ReportDialog } from './report-dialog';

export function PostDetail({ postId }: { postId: string }) {
  const t = useTranslations('postDetail');
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const [body, setBody] = useState('');
  const [reportOpen, setReportOpen] = useState(search.get('report') === '1');

  const post = useQuery({ queryKey: qk.post(postId), queryFn: () => browserApi().posts.get(postId), retry: false });
  const comments = useQuery({ queryKey: qk.comments(postId), queryFn: () => browserApi().posts.comments(postId, { limit: 50 }), enabled: post.isSuccess });
  const add = useMutation({
    mutationFn: () => browserApi().posts.addComment(postId, { body: body.trim() }),
    onSuccess: () => {
      setBody('');
      void queryClient.invalidateQueries({ queryKey: qk.comments(postId) });
    },
  });

  if (post.isPending) return <Skeleton className="h-64 w-full rounded-card" />;
  if (post.isError) {
    const missing = isApiError(post.error) && post.error.status === 404;
    return (
      <EmptyState
        title={missing ? t('notFoundTitle') : t('errorTitle')}
        description={missing ? t('notFoundBody') : t('errorBody')}
        action={
          <Button asChild variant="secondary">
            <Link href="/feed">{t('back')}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Link href="/feed" className="flex w-fit items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden="true" />
        {t('back')}
      </Link>
      <PostCard post={post.data} />
      <section aria-labelledby="comments-heading" className="flex flex-col gap-4 rounded-card border border-border bg-surface p-4">
        <h2 id="comments-heading" className="font-display text-xl font-semibold">
          {t('comments')}
        </h2>
        {post.data.viewer.can_comment ? (
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (body.trim()) add.mutate();
            }}
          >
            <label htmlFor="comment-body" className="sr-only">
              {t('addComment')}
            </label>
            <Textarea id="comment-body" value={body} maxLength={LIMITS.comment.max} rows={2} placeholder={t('addComment')} onChange={(e) => setBody(e.target.value)} />
            {add.isError ? <Alert tone="danger">{t('commentError')}</Alert> : null}
            <Button type="submit" size="sm" className="self-end" loading={add.isPending} disabled={!body.trim()}>
              {t('send')}
            </Button>
          </form>
        ) : null}
        {comments.isPending ? <Skeleton className="h-16 w-full" /> : null}
        {comments.data?.data.length === 0 ? <p className="text-sm text-muted-foreground">{t('noComments')}</p> : null}
        <ul className="flex flex-col gap-4">
          {comments.data?.data.map((c) => (
            <li key={c.id} className="flex gap-3">
              <Avatar name={c.author?.display_name ?? '?'} size={32} />
              <div className="flex flex-col">
                <span className="text-sm">
                  <span className="font-semibold">{c.author?.display_name ?? t('deletedUser')}</span>{' '}
                  <time dateTime={c.created_at} className="text-xs text-muted-foreground">
                    {format.relativeTime(new Date(c.created_at), now)}
                  </time>
                </span>
                <p className="text-sm whitespace-pre-line" lang={c.language}>
                  {c.deleted ? t('deletedComment') : c.body}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </section>
      {!post.data.viewer.is_author ? (
        <ReportDialog open={reportOpen} onOpenChange={setReportOpen} targetType="post" targetId={postId} />
      ) : null}
    </div>
  );
}
