'use client';

import { useState } from 'react';
import { useInfiniteQuery, useMutation, useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import type { Page, UserSummary } from '@travelbuddy/domain-types';
import { Alert, Avatar, Button, Card, Skeleton } from '@travelbuddy/ui';
import { browserApi } from '@/lib/api-browser';
import { qk } from '@/lib/query-keys';

type BlocksData = InfiniteData<Page<UserSummary>, string | null>;

/** Privacy centre: the accounts you've blocked, with unblock (page inventory, Privacy settings; SAFE-001). */
export function BlockedUsers() {
  const t = useTranslations('settings.blocked');
  const queryClient = useQueryClient();
  const [failed, setFailed] = useState<string | null>(null);

  const blocks = useInfiniteQuery({
    queryKey: qk.blocks(),
    queryFn: ({ pageParam }) => browserApi().users.blocks({ cursor: pageParam ?? undefined, limit: 50 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.page.has_more ? last.page.next_cursor : undefined),
  });

  const unblock = useMutation({
    mutationFn: (user: UserSummary) => browserApi().users.unblock(user.id),
    onMutate: async (user) => {
      setFailed(null);
      await queryClient.cancelQueries({ queryKey: qk.blocks() });
      const previous = queryClient.getQueryData<BlocksData>(qk.blocks());
      queryClient.setQueryData<BlocksData>(qk.blocks(), (data) =>
        data ? { ...data, pages: data.pages.map((p) => ({ ...p, data: p.data.filter((u) => u.id !== user.id) })) } : data,
      );
      return { previous };
    },
    onError: (_e, user, context) => {
      if (context?.previous) queryClient.setQueryData(qk.blocks(), context.previous);
      setFailed(user.display_name);
    },
    // Their content may come back into the feed.
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.feedAll() }),
  });

  const users = blocks.data?.pages.flatMap((p) => p.data) ?? [];

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="text-sm text-muted-foreground">{t('hint')}</p>
      {failed ? <Alert tone="danger">{t('unblockError', { name: failed })}</Alert> : null}
      {blocks.isPending ? (
        <Skeleton className="h-12 w-full" />
      ) : blocks.isError ? (
        <Alert tone="danger">{t('error')}</Alert>
      ) : users.length === 0 ? (
        <p className="text-sm">{t('empty')}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border" aria-label={t('heading')}>
          {users.map((user) => (
            <li key={user.id} className="flex items-center gap-3 py-2">
              <Avatar name={user.display_name} src={user.avatar?.url} size={36} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{user.display_name}</span>
                <span className="truncate text-xs text-muted-foreground">@{user.handle}</span>
              </span>
              <Button type="button" variant="secondary" size="sm" onClick={() => unblock.mutate(user)} aria-label={t('unblockLabel', { name: user.display_name })}>
                {t('unblock')}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {blocks.hasNextPage ? (
        <Button type="button" variant="ghost" onClick={() => blocks.fetchNextPage()} loading={blocks.isFetchingNextPage}>
          {t('loadMore')}
        </Button>
      ) : null}
    </Card>
  );
}
