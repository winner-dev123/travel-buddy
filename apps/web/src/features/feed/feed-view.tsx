'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { Compass, LocateFixed, MapPin, RefreshCw, X } from 'lucide-react';
import { isApiError, type FeedQuery } from '@travelbuddy/api-client';
import { FEED_RADII_KM, FEED_TABS, type FeedTab } from '@travelbuddy/domain-types';
import { FEED_TAB_SLUGS, feedTabFromSlug } from '@travelbuddy/validation';
import { Alert, Button, EmptyState, NativeSelect, Skeleton, cn } from '@travelbuddy/ui';
import { DestinationSearch } from '@/components/destination-search';
import { usePathname, useRouter } from '@/i18n/navigation';
import { browserApi } from '@/lib/api-browser';
import { qk } from '@/lib/query-keys';
import { useViewer } from '@/features/shell/viewer-context';
import { Composer } from './composer';
import { getFeedLocationPreference } from './location-preference';
import { PostCard } from './post-card';
import { useDeviceLocation } from './use-device-location';

/**
 * Location-based social feed (brief §10). Relevance comes from the selected destination or the
 * device's current (rounded, request-scoped) position — never nationality or IP address.
 */
export function FeedView() {
  const t = useTranslations('feed');
  const viewer = useViewer();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const tab = feedTabFromSlug(search.get('tab'));
  const destinationId = search.get('d');
  const [radius, setRadius] = useState<number>(10);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [picking, setPicking] = useState(false);
  const location = useDeviceLocation();
  const { locateIfGranted } = location;

  useEffect(() => {
    // Use device location automatically only when the user opted in on this browser AND the
    // permission was already granted — never surprise-prompt.
    if (getFeedLocationPreference()) void locateIfGranted();
  }, [locateIfGranted]);

  const setParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(search.toString());
    if (value === null) params.delete(key);
    else params.set(key, value);
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const useNear = tab === 'nearby' || (tab === 'for_you' && !destinationId && location.near !== null);
  const query: Omit<FeedQuery, 'cursor'> = useMemo(
    () => ({
      tab,
      destination_id: tab === 'for_you' || tab === 'destinations' ? destinationId : null,
      near: useNear ? location.near : null,
      radius_km: tab === 'nearby' ? radius : null,
    }),
    [tab, destinationId, useNear, location.near, radius],
  );

  const feed = useInfiniteQuery({
    queryKey: qk.feed(query),
    queryFn: ({ pageParam, signal }) => browserApi().feed.get({ ...query, cursor: pageParam, limit: 10 }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.page.has_more ? last.page.next_cursor : undefined),
    enabled: tab !== 'nearby' || location.near !== null,
  });

  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && feed.hasNextPage && !feed.isFetchingNextPage) void feed.fetchNextPage();
    }, { rootMargin: '600px' });
    io.observe(el);
    return () => io.disconnect();
  }, [feed]);

  const context = feed.data?.pages[0]?.context;
  const posts = (feed.data?.pages.flatMap((p) => p.data) ?? []).filter((p) => !hidden.has(p.id));
  const hide = (id: string) => setHidden((s) => new Set(s).add(id));

  const contextLine = () => {
    if (!context) return null;
    if (context.source === 'following') return t('context.following');
    if (context.source === 'global') return t('context.global');
    if (context.source === 'interests') return t('context.interests');
    const name = context.destination?.name ?? '';
    if (context.source === 'gps') return tab === 'nearby' ? t('context.nearby', { radius: context.radius_km ?? radius }) : t('context.gps', { name });
    if (context.source === 'upcoming_trip') return t('context.trip', { name });
    return t('context.selected', { name });
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-5 px-4 py-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-3xl font-semibold">{t('title', { name: viewer.displayName.split(' ')[0] ?? '' })}</h1>
      </div>

      <nav aria-label={t('tabsLabel')} className="-mx-1 flex gap-1 overflow-x-auto px-1">
        {FEED_TABS.map((key: FeedTab) => (
          <button
            key={key}
            type="button"
            aria-current={tab === key ? 'page' : undefined}
            onClick={() => setParam('tab', key === 'for_you' ? null : FEED_TAB_SLUGS[key])}
            className={cn(
              'shrink-0 rounded-pill px-4 py-2 text-sm font-semibold transition-colors',
              tab === key ? 'bg-foreground text-background' : 'bg-surface-muted text-muted-foreground hover:text-foreground',
            )}
          >
            {t(`tabs.${key}`)}
          </button>
        ))}
      </nav>

      {/* Location context: always tells the traveler WHY they see what they see. */}
      {tab !== 'following' ? (
        <section aria-label={t('locationLabel')} className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-2 text-sm font-semibold" aria-live="polite">
              <MapPin className="size-4 text-primary" aria-hidden="true" />
              {feed.isPending && tab !== 'nearby' ? t('context.loading') : (contextLine() ?? t('context.pickPrompt'))}
            </p>
            <div className="flex flex-wrap gap-2">
              {tab !== 'nearby' ? (
                <Button size="sm" variant="secondary" onClick={() => setPicking((p) => !p)} aria-expanded={picking}>
                  {t('changeDestination')}
                </Button>
              ) : null}
              {destinationId ? (
                <Button size="sm" variant="ghost" onClick={() => setParam('d', null)}>
                  <X aria-hidden="true" />
                  {t('clearDestination')}
                </Button>
              ) : null}
              {tab === 'for_you' && !destinationId ? (
                <Button size="sm" variant={location.near ? 'soft' : 'ghost'} onClick={location.near ? location.clear : location.locate} loading={location.status === 'locating'}>
                  <LocateFixed aria-hidden="true" />
                  {location.near ? t('stopUsingLocation') : t('useLocation')}
                </Button>
              ) : null}
            </div>
          </div>
          {picking ? (
            <DestinationSearch
              autoFocus
              label={t('changeDestination')}
              onSelect={(d) => {
                setPicking(false);
                setParam('d', d.id);
              }}
            />
          ) : null}
          {tab === 'nearby' ? (
            <div className="flex flex-wrap items-center gap-3">
              {location.near ? (
                <label className="flex items-center gap-2 text-sm">
                  {t('radius')}
                  <NativeSelect className="h-9 w-auto" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
                    {FEED_RADII_KM.map((r) => (
                      <option key={r} value={r}>
                        {t('radiusKm', { km: r })}
                      </option>
                    ))}
                  </NativeSelect>
                </label>
              ) : (
                <Button size="sm" onClick={location.locate} loading={location.status === 'locating'}>
                  <LocateFixed aria-hidden="true" />
                  {t('shareLocation')}
                </Button>
              )}
              <p className="text-xs text-muted-foreground">{t('locationPrivacy')}</p>
            </div>
          ) : null}
          {location.status === 'denied' ? <Alert tone="info">{t('locationDenied')}</Alert> : null}
          {location.status === 'unavailable' ? <Alert tone="info">{t('locationUnavailable')}</Alert> : null}
        </section>
      ) : null}

      <Composer defaultDestination={context?.destination ?? viewer.browseDestination ?? null} />

      {tab === 'nearby' && !location.near ? (
        <EmptyState icon={<LocateFixed />} title={t('empty.nearbyTitle')} description={t('empty.nearbyBody')} />
      ) : feed.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true" aria-label={t('loading')}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-card border border-border bg-surface p-4">
              <div className="flex items-center gap-3">
                <Skeleton className="size-10 rounded-full" />
                <div className="flex flex-1 flex-col gap-2">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-3 w-1/4" />
                </div>
              </div>
              <Skeleton className="mt-4 h-16 w-full" />
            </div>
          ))}
        </div>
      ) : feed.isError ? (
        <Alert tone="danger" title={t('error.title')}>
          <p>{isApiError(feed.error) && feed.error.requestId ? t('error.bodyRef', { id: feed.error.requestId }) : t('error.body')}</p>
          <Button size="sm" variant="secondary" className="mt-3" onClick={() => void feed.refetch()}>
            <RefreshCw aria-hidden="true" />
            {t('error.retry')}
          </Button>
        </Alert>
      ) : posts.length === 0 ? (
        <EmptyState
          icon={<Compass />}
          title={t(`empty.${tab}Title`, { name: context?.destination?.name ?? '' })}
          description={t(`empty.${tab}Body`)}
          action={
            destinationId ? (
              <Button variant="secondary" onClick={() => setParam('d', null)}>
                {t('clearDestination')}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="flex flex-col gap-4">
          {posts.map((p) => (
            <PostCard key={p.id} post={p} onHidden={hide} />
          ))}
          <div ref={sentinel} />
          {feed.hasNextPage ? (
            <Button variant="secondary" onClick={() => void feed.fetchNextPage()} loading={feed.isFetchingNextPage}>
              {t('loadMore')}
            </Button>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">{t('end')}</p>
          )}
        </div>
      )}
    </div>
  );
}
