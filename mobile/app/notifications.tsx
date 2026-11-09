import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useEffect } from 'react';
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
import { Notice } from '@/components/Form';
import {
  accountKeys,
  fetchNotifications,
  markAllRead,
  type AppNotification,
} from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-120 Notification center (NOTIF-001). Opening it marks everything as read. */
export default function NotificationsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: accountKeys.notifications,
    queryFn: () => fetchNotifications(getApiClient()),
  });

  const hasUnread = (list.data?.data ?? []).some((item) => item.read_at === null);
  useEffect(() => {
    if (!hasUnread) return;
    void markAllRead(getApiClient())
      .then(() => queryClient.setQueryData(accountKeys.unread, 0))
      .catch(() => undefined); // still unread next time; nothing to tell the user
  }, [hasUnread, queryClient]);

  const open = (item: AppNotification) => {
    if (item.entity_type === 'post' && item.entity_id) {
      router.push({ pathname: '/post/[id]', params: { id: item.entity_id } });
    } else if (item.entity_type === 'user' && item.entity_id) {
      router.push({ pathname: '/user/[id]', params: { id: item.entity_id } });
    }
  };

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('notifications.title') }} />
      <FlatList<AppNotification>
        data={list.data?.data ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
        refreshControl={
          <RefreshControl refreshing={list.isRefetching} onRefresh={() => void list.refetch()} />
        }
        renderItem={({ item }) => (
          <Pressable
            onPress={() => open(item)}
            accessibilityRole="button"
            accessibilityLabel={`${item.title}. ${item.body}`}
            style={[
              styles.item,
              {
                backgroundColor: item.read_at ? theme.colors.background : theme.colors.infoSurface,
                borderColor: theme.colors.divider,
              },
            ]}
            testID={`notification-${item.id}`}
          >
            <Avatar user={item.actor} size={36} />
            <View style={styles.fill}>
              <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                {item.title}
              </Text>
              <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                {item.body}
              </Text>
            </View>
          </Pressable>
        )}
        ListEmptyComponent={
          list.isPending ? (
            <ActivityIndicator color={theme.colors.primary} />
          ) : list.isError ? (
            <Notice tone="error">{t('notifications.error')}</Notice>
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="notifications-empty"
            >
              {t('notifications.empty')}
            </Text>
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  item: {
    flexDirection: 'row',
    gap: 12,
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'flex-start',
  },
});
