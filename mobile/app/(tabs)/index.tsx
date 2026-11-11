import Ionicons from '@expo/vector-icons/Ionicons';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Chip } from '@/components/Chip';
import { FeatureGate } from '@/components/FeatureGate';
import { Button, Notice } from '@/components/Form';
import { ScreenTitle } from '@/components/ScreenTitle';
import { accountKeys, unreadCount } from '@/features/account/api';
import { feedKeys, fetchFeed, fetchPublicPosts } from '@/features/feed/api';
import { PostCard } from '@/features/feed/PostCard';
import { getCoarsePosition, isFresh, type CoarsePosition } from '@/features/feed/location';
import type { FeedPage, Post, PostKind } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-020 Home: destination-based travel feed (Phase 1). */
export default function HomeScreen() {
  return (
    <FeatureGate feature="feed">
      <HomeFeed />
    </FeatureGate>
  );
}

const TABS = ['for_you', 'nearby', 'following'] as const;
const FILTERS: (PostKind | null)[] = [
  null,
  'tip',
  'experience',
  'attraction_recommendation',
  'restaurant_recommendation',
];
type HomeTab = (typeof TABS)[number];

function HomeFeed() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const status = useSessionStore((state) => state.status);
  const signedIn = status === 'signed_in';
  const [tab, setTab] = useState<HomeTab>('for_you');
  const [category, setCategory] = useState<PostKind | null>(null);
  const nearby = signedIn && tab === 'nearby';
  const queryClient = useQueryClient();

  // Asked only when the user opens Nearby (LOC-001): no location prompt at launch.
  const position = useQuery({
    queryKey: ['device', 'coarse-position'],
    queryFn: getCoarsePosition,
    enabled: nearby,
    staleTime: 5 * 60_000,
  });
  const near = position.data?.status === 'granted' ? position.data.near : undefined;
  const deviceFix = position.data?.status === 'granted' ? position.data.fix : undefined;

  const query = useInfiniteQuery({
    queryKey: feedKeys.list(signedIn ? tab : 'guest', near, category),
    queryFn: async ({ pageParam }) => {
      if (!signedIn) return fetchPublicPosts(getApiClient(), pageParam);
      let fix = nearby ? deviceFix : undefined;
      if (fix && !isFresh(fix)) {
        // LOC-007: the API refuses fixes older than 15 minutes; locate again first.
        const again = await getCoarsePosition();
        queryClient.setQueryData<CoarsePosition>(['device', 'coarse-position'], again);
        fix = again.status === 'granted' ? again.fix : undefined;
      }
      return fetchFeed(getApiClient(), tab, pageParam, {
        near: nearby ? (fix?.near ?? near) : undefined,
        fix,
        categories: category ? [category] : undefined,
      });
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: FeedPage) =>
      last.page.has_more ? (last.page.next_cursor ?? undefined) : undefined,
    enabled: status !== 'restoring' && (!nearby || near !== undefined),
  });
  const uncovered =
    query.error instanceof ApiProblem && query.error.code === 'location_unresolvable';

  // A snapshot reset means the ranking was recomputed: start over instead of appending.
  const pages = query.data?.pages ?? [];
  const resetAt = pages.findIndex((page, index) => index > 0 && page.page.reset);
  const visible = resetAt > 0 ? pages.slice(0, resetAt) : pages;
  const posts: Post[] = visible.flatMap((page) => page.data);
  const context = pages[0]?.context;

  const open = (post: Post) => router.push({ pathname: '/post/[id]', params: { id: post.id } });
  const openAuthor = (userId: string) =>
    router.push({ pathname: '/user/[id]', params: { id: userId } });
  const unread = useQuery({
    queryKey: accountKeys.unread,
    queryFn: () => unreadCount(getApiClient()),
    enabled: signedIn,
  });

  const header = (
    <View style={{ gap: theme.spacing[4], paddingBottom: theme.spacing[4] }}>
      <ScreenTitle
        eyebrow={t('common.appName')}
        title={t('feed.title')}
        trailing={
          signedIn ? (
            <Pressable
              onPress={() => router.push('/notifications')}
              accessibilityRole="button"
              accessibilityLabel={
                unread.data
                  ? t('notifications.unreadA11y', { count: unread.data })
                  : t('notifications.title')
              }
              hitSlop={8}
              style={[
                styles.bell,
                { backgroundColor: theme.colors.surface, borderColor: theme.colors.divider },
              ]}
              testID="feed-notifications"
            >
              <Ionicons name="notifications-outline" size={22} color={theme.colors.textPrimary} />
              {unread.data ? (
                <View style={[styles.badge, { backgroundColor: theme.colors.danger }]}>
                  <Text
                    style={[theme.typography.caption, { color: theme.colors.onDanger }]}
                    testID="feed-unread"
                  >
                    {unread.data > 99 ? '99+' : unread.data}
                  </Text>
                </View>
              ) : null}
            </Pressable>
          ) : undefined
        }
      />
      {signedIn ? (
        <View style={styles.chips} accessibilityRole="tablist">
          {TABS.map((value) => (
            <Chip
              key={value}
              label={t(`feed.tabs.${value}`)}
              onPress={() => setTab(value)}
              selected={value === tab}
              accessibilityRole="tab"
              testID={`feed-tab-${value}`}
            />
          ))}
        </View>
      ) : (
        <Notice tone="info" testID="feed-guest-notice">
          {t('feed.guestNotice')}
        </Notice>
      )}
      {signedIn ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chips}
          testID="feed-filters"
        >
          {FILTERS.map((value) => (
            <Chip
              key={value ?? 'all'}
              label={value ? t(`post.kinds.${value}`) : t('feed.filters.all')}
              onPress={() => setCategory(value)}
              selected={value === category}
              tone="quiet"
              accessibilityRole="radio"
              testID={`feed-filter-${value ?? 'all'}`}
            />
          ))}
        </ScrollView>
      ) : null}
      {nearby ? (
        position.isPending ? (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('feed.nearby.locating')}
          </Text>
        ) : position.data?.status === 'denied' ? (
          <Notice tone="info" testID="feed-nearby-denied">
            {t('feed.nearby.denied')}
          </Notice>
        ) : position.data?.status === 'unavailable' ? (
          <Notice tone="info" testID="feed-nearby-unavailable">
            {t('feed.nearby.unavailable')}
          </Notice>
        ) : uncovered ? (
          <Notice tone="info" testID="feed-nearby-uncovered">
            {t('feed.nearby.uncovered')}
          </Notice>
        ) : (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('feed.nearby.privacy')}
          </Text>
        )
      ) : null}
      {context ? (
        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          testID="feed-context"
        >
          {context.destination
            ? t(`feed.source.${context.source}`, { place: context.destination.name })
            : t(`feed.source.${context.source}`, { place: '' })}
        </Text>
      ) : null}
      {!signedIn ? (
        <Button
          label={t('account.goToSignIn')}
          onPress={() => router.push('/sign-in')}
          variant="secondary"
        />
      ) : null}
    </View>
  );

  return (
    <SafeAreaView
      edges={['top']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <FlatList
        data={posts}
        keyExtractor={(post) => post.id}
        renderItem={({ item }) => (
          <PostCard
            post={item}
            onOpen={open}
            onOpenAuthor={signedIn ? openAuthor : undefined}
            interactive={signedIn}
          />
        )}
        ItemSeparatorComponent={() => <View style={{ height: theme.spacing[5] }} />}
        ListHeaderComponent={header}
        contentContainerStyle={{ padding: theme.spacing[4], paddingBottom: theme.spacing[16] }}
        onEndReached={() => {
          if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
        }}
        onEndReachedThreshold={0.5}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching && !query.isFetchingNextPage}
            onRefresh={() => void query.refetch()}
            tintColor={theme.colors.primary}
            colors={[theme.colors.primary]}
            progressBackgroundColor={theme.colors.surfaceRaised}
          />
        }
        ListEmptyComponent={
          query.isLoading || (nearby && position.isPending) ? (
            <ActivityIndicator color={theme.colors.primary} testID="feed-loading" />
          ) : nearby &&
            (uncovered || position.data?.status !== 'granted') ? undefined : query.isError ? (
            <Notice tone="error" testID="feed-error">
              {t('feed.error')}
            </Notice>
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="feed-empty"
            >
              {tab === 'following' ? t('feed.emptyFollowing') : t('feed.empty')}
            </Text>
          )
        }
        ListFooterComponent={
          query.isFetchingNextPage ? <ActivityIndicator color={theme.colors.primary} /> : undefined
        }
        testID="feed-list"
      />
      {signedIn ? (
        <Pressable
          onPress={() => router.push('/compose')}
          accessibilityRole="button"
          accessibilityLabel={t('compose.open')}
          style={({ pressed }) => [
            styles.fab,
            theme.elevation[3],
            { backgroundColor: theme.colors.primary, opacity: pressed ? 0.85 : 1 },
          ]}
          testID="feed-compose"
        >
          <LinearGradient
            colors={theme.accentGradient}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={[StyleSheet.absoluteFill, styles.fabFill]}
          />
          <Ionicons name="add" size={28} color={theme.colors.onPrimary} />
        </Pressable>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', gap: 8 },
  bell: {
    width: 44,
    height: 44,
    borderRadius: 22,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badge: {
    position: 'absolute',
    top: -4,
    right: -4,
    borderRadius: 999,
    minWidth: 18,
    paddingHorizontal: 4,
    alignItems: 'center',
  },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 20,
    width: 60,
    height: 60,
    borderRadius: 30,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fabFill: { borderRadius: 30 },
});
