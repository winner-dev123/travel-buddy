import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { accountKeys, listBlocks, unblock } from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import { feedKeys } from '@/features/feed/api';
import type { UserSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-112 Blocked accounts: who I blocked, with unblock (SAFE-001). */
export default function BlockedScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const blocks = useQuery({
    queryKey: accountKeys.blocks,
    queryFn: () => listBlocks(getApiClient()),
  });
  const remove = useMutation({
    mutationFn: (userId: string) => unblock(getApiClient(), userId),
    onSuccess: (_, userId) => {
      queryClient.setQueryData(accountKeys.blocks, (old: typeof blocks.data) =>
        old ? { ...old, data: old.data.filter((user) => user.id !== userId) } : old,
      );
      void queryClient.invalidateQueries({ queryKey: feedKeys.all });
    },
  });

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('account.blocked') }} />
      <FlatList<UserSummary>
        data={blocks.data?.data ?? []}
        keyExtractor={(user) => user.id}
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        ListHeaderComponent={
          <View style={{ gap: theme.spacing[3] }}>
            <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
              {t('account.blockedHint')}
            </Text>
            {remove.isError ? <Notice tone="error">{t('account.unblockFailed')}</Notice> : null}
          </View>
        }
        renderItem={({ item }) => (
          <View style={styles.row} testID={`blocked-${item.id}`}>
            <Avatar user={item} />
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {item.display_name}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                @{item.handle}
              </Text>
            </View>
            <Button
              label={t('account.unblock')}
              variant="secondary"
              onPress={() => remove.mutate(item.id)}
              busy={remove.isPending && remove.variables === item.id}
              testID={`unblock-${item.id}`}
            />
          </View>
        )}
        ListEmptyComponent={
          blocks.isPending ? (
            <ActivityIndicator color={theme.colors.primary} />
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="blocked-empty"
            >
              {t('account.noBlocked')}
            </Text>
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
});
