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
import { PushBanner } from '@/features/push/PushBanner';
import { notificationRoute } from '@/features/push/push';
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
    const route = notificationRoute(item.entity_type, item.entity_id);
    if (route) router.push(route);
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
        ListHeaderComponent={<PushBanner />}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
        refreshControl={
          <RefreshControl
            refreshing={list.isRefetching}
            onRefresh={() => void list.refetch()}
            tintColor={theme.colors.primary}
            colors={[theme.colors.primary]}
            progressBackgroundColor={theme.colors.surfaceRaised}
          />
        }
        renderItem={({ item }) => {
          const unread = item.read_at === null;
          return (
            <Pressable
              onPress={() => open(item)}
              accessibilityRole="button"
              accessibilityLabel={`${unread ? `${t('notifications.unread')}. ` : ''}${item.title}. ${item.body}`}
              style={({ pressed }) => [
                styles.item,
                {
                  padding: theme.spacing[3],
                  gap: theme.spacing[3],
                  borderRadius: theme.radii.lg,
                  backgroundColor:
                    unread || pressed ? theme.colors.surfaceRaised : theme.colors.surface,
                  borderColor: theme.colors.divider,
                },
              ]}
              testID={`notification-${item.id}`}
            >
              <Avatar user={item.actor} size={40} />
              <View style={styles.text}>
                <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                  {item.title}
                </Text>
                <Text
                  style={[
                    theme.typography.body,
                    { color: unread ? theme.colors.textPrimary : theme.colors.textSecondary },
                  ]}
                >
                  {item.body}
                </Text>
              </View>
              {unread ? (
                <View
                  style={[styles.dot, { backgroundColor: theme.colors.primary }]}
                  testID={`notification-unread-${item.id}`}
                />
              ) : null}
            </Pressable>
          );
        }}
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
  item: { flexDirection: 'row', borderWidth: StyleSheet.hairlineWidth, alignItems: 'flex-start' },
  text: { flex: 1, gap: 2 },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
});
