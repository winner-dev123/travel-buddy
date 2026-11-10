import { useInfiniteQuery } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, FlatList, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { feedKeys, fetchBookmarks } from '@/features/feed/api';
import { PostCard } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-102 Saved stories: the stories I bookmarked (POST-005), newest save first. Only I can
 * see this list. */
export default function SavedStoriesScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const saved = useInfiniteQuery({
    queryKey: feedKeys.bookmarks,
    queryFn: ({ pageParam }) => fetchBookmarks(getApiClient(), pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.page.next_cursor ?? undefined,
  });
  const posts = saved.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('bookmarks.title') }} />
      <FlatList
        data={posts}
        keyExtractor={(post) => post.id}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        renderItem={({ item }) => (
          <PostCard
            post={item}
            onOpen={(post) => router.push({ pathname: '/post/[id]', params: { id: post.id } })}
            onOpenAuthor={(userId) =>
              router.push({ pathname: '/user/[id]', params: { id: userId } })
            }
          />
        )}
        onEndReached={() => {
          if (saved.hasNextPage && !saved.isFetchingNextPage) void saved.fetchNextPage();
        }}
        ListEmptyComponent={
          saved.isPending ? (
            <ActivityIndicator />
          ) : saved.isError ? (
            <Notice tone="error" testID="bookmarks-error">
              {t('bookmarks.error')}
            </Notice>
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="bookmarks-empty"
            >
              {t('bookmarks.empty')}
            </Text>
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
