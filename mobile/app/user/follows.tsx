import { useInfiniteQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { listFollows } from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

/** Who follows a traveller, or whom they follow (PROF-003). Private accounts' lists are only
 * served to their approved followers; the server decides. */
export default function FollowsScreen() {
  const { id, kind } = useLocalSearchParams<{ id: string; kind: 'followers' | 'following' }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const list = useInfiniteQuery({
    queryKey: ['user', id, kind],
    queryFn: ({ pageParam }) => listFollows(getApiClient(), id, kind, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.page.next_cursor ?? undefined,
  });
  const people = list.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: kind === 'following' ? t('follows.following') : t('follows.followers'),
        }}
      />
      <FlatList
        data={people}
        keyExtractor={(person) => person.id}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => router.push({ pathname: '/user/[id]', params: { id: item.id } })}
            accessibilityRole="link"
            style={styles.row}
            testID={`follows-${item.id}`}
          >
            <Avatar user={item} size={40} />
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {item.display_name}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                @{item.handle}
              </Text>
            </View>
          </Pressable>
        )}
        onEndReached={() => {
          if (list.hasNextPage && !list.isFetchingNextPage) void list.fetchNextPage();
        }}
        ListEmptyComponent={
          list.isPending ? (
            <ActivityIndicator />
          ) : list.isError ? (
            <Notice tone="error" testID="follows-error">
              {t('follows.error')}
            </Notice>
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="follows-empty"
            >
              {t('follows.empty')}
            </Text>
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 4 },
});
