import Ionicons from '@expo/vector-icons/Ionicons';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { FeatureGate } from '@/components/FeatureGate';
import { Button, Notice } from '@/components/Form';
import { accountKeys, unreadCount } from '@/features/account/api';
import { feedKeys, fetchFeed, fetchPublicPosts } from '@/features/feed/api';
import { PostCard } from '@/features/feed/PostCard';
import type { FeedPage, Post } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-020 Home: destination-based travel feed (Phase 1). */
export default function HomeScreen() {
  return (
    <FeatureGate feature="feed">
      <HomeFeed />
    </FeatureGate>
  );
}

const TABS = ['for_you', 'following'] as const;
type HomeTab = (typeof TABS)[number];

function HomeFeed() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const status = useSessionStore((state) => state.status);
  const signedIn = status === 'signed_in';
  const [tab, setTab] = useState<HomeTab>('for_you');

  const query = useInfiniteQuery({
    queryKey: feedKeys.list(signedIn ? tab : 'guest'),
    queryFn: ({ pageParam }) =>
      signedIn
        ? fetchFeed(getApiClient(), tab, pageParam)
        : fetchPublicPosts(getApiClient(), pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: FeedPage) =>
      last.page.has_more ? (last.page.next_cursor ?? undefined) : undefined,
    enabled: status !== 'restoring',
  });

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
    <View style={{ gap: theme.spacing[3], paddingBottom: theme.spacing[3] }}>
      <View style={styles.titleRow}>
        <Text
          style={[theme.typography.title1, styles.flex, { color: theme.colors.textPrimary }]}
          accessibilityRole="header"
        >
          {t('feed.title')}
        </Text>
        {signedIn ? (
          <Pressable
            onPress={() => router.push('/notifications')}
            accessibilityRole="button"
            accessibilityLabel={
              unread.data
                ? t('notifications.unreadA11y', { count: unread.data })
                : t('notifications.title')
            }
            hitSlop={8}
            testID="feed-notifications"
          >
            <Ionicons name="notifications-outline" size={26} color={theme.colors.textPrimary} />
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
        ) : null}
      </View>
      {signedIn ? (
        <View style={styles.chips} accessibilityRole="tablist">
          {TABS.map((value) => {
            const selected = value === tab;
            return (
              <Pressable
                key={value}
                onPress={() => setTab(value)}
                accessibilityRole="tab"
                accessibilityState={{ selected }}
                style={[
                  styles.chip,
                  {
                    backgroundColor: selected ? theme.colors.primary : theme.colors.surface,
                    borderColor: selected ? theme.colors.primary : theme.colors.borderStrong,
                  },
                ]}
                testID={`feed-tab-${value}`}
              >
                <Text
                  style={[
                    theme.typography.label,
                    { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
                  ]}
                >
                  {t(`feed.tabs.${value}`)}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <Notice tone="info" testID="feed-guest-notice">
          {t('feed.guestNotice')}
        </Notice>
      )}
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
        ItemSeparatorComponent={() => <View style={{ height: theme.spacing[3] }} />}
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
          />
        }
        ListEmptyComponent={
          query.isPending ? (
            <ActivityIndicator color={theme.colors.primary} testID="feed-loading" />
          ) : query.isError ? (
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
          style={[styles.fab, theme.elevation[2], { backgroundColor: theme.colors.primary }]}
          testID="feed-compose"
        >
          <Ionicons name="add" size={28} color={theme.colors.onPrimary} />
        </Pressable>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', gap: 8 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  flex: { flex: 1 },
  badge: {
    position: 'absolute',
    top: -6,
    right: -8,
    borderRadius: 999,
    minWidth: 18,
    paddingHorizontal: 4,
    alignItems: 'center',
  },
  chip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
    minHeight: 36,
  },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 20,
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
