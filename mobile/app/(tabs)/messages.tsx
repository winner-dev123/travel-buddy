import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
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
import { ServerFeature } from '@/features/flags/serverFlags';
import { Notice } from '@/components/Form';
import { Avatar } from '@/features/feed/PostCard';
import {
  listConversations,
  messageKeys,
  POLL_INBOX_MS,
  type Conversation,
} from '@/features/messages/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-080 Messages: direct messages now; group chats and activities arrive with groups. */
export default function MessagesScreen() {
  return (
    <FeatureGate feature="messaging">
      <ServerFeature anyOf={['direct_messages', 'travel_groups']}>
        <Inbox />
      </ServerFeature>
    </FeatureGate>
  );
}

function Preview({ conversation }: { conversation: Conversation }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const me = useSessionStore((state) => state.me?.account.id);
  const last = conversation.last_message;
  const text = !last
    ? ''
    : last.deleted
      ? t('messages.deleted')
      : last.kind === 'image' && !last.snippet
        ? t('messages.photo')
        : (last.snippet ?? '');
  return (
    <Text
      numberOfLines={1}
      style={[
        theme.typography.body,
        {
          color: conversation.unread_count ? theme.colors.textPrimary : theme.colors.textSecondary,
        },
      ]}
    >
      {last && last.sender_id === me && !last.deleted ? t('messages.you', { text }) : text}
    </Text>
  );
}

function Inbox() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const inbox = useQuery({
    queryKey: messageKeys.inbox,
    queryFn: () => listConversations(getApiClient()),
    refetchInterval: POLL_INBOX_MS,
  });

  return (
    <SafeAreaView
      edges={['top']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <FlatList<Conversation>
        data={inbox.data?.data ?? []}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
        refreshControl={
          <RefreshControl refreshing={inbox.isRefetching} onRefresh={() => void inbox.refetch()} />
        }
        ListHeaderComponent={
          <Text
            accessibilityRole="header"
            style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
          >
            {t('messages.title')}
          </Text>
        }
        ListEmptyComponent={
          inbox.isPending ? (
            <ActivityIndicator color={theme.colors.primary} />
          ) : inbox.isError ? (
            <Notice tone="error">{t('messages.loadFailed')}</Notice>
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="messages-empty"
            >
              {t('messages.empty')}
            </Text>
          )
        }
        renderItem={({ item }) => {
          const name = item.title ?? item.counterpart?.display_name ?? t('messages.deletedUser');
          const when = item.last_message_at
            ? new Date(item.last_message_at).toLocaleDateString(i18n.language, {
                month: 'short',
                day: 'numeric',
              })
            : '';
          return (
            <Pressable
              onPress={() => router.push({ pathname: '/chat/[id]', params: { id: item.id } })}
              accessibilityRole="button"
              accessibilityLabel={
                item.unread_count
                  ? `${name}, ${t('messages.unread', { count: item.unread_count })}`
                  : name
              }
              style={[styles.row, { borderBottomColor: theme.colors.divider }]}
              testID={`conversation-${item.id}`}
            >
              <Avatar
                user={
                  item.counterpart ??
                  (item.title
                    ? { id: item.id, handle: '', display_name: item.title, avatar: null }
                    : null)
                }
              />
              <View style={styles.fill}>
                <View style={styles.top}>
                  <Text
                    numberOfLines={1}
                    style={[
                      styles.fill,
                      theme.typography.bodyStrong,
                      { color: theme.colors.textPrimary },
                    ]}
                  >
                    {name}
                  </Text>
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {when}
                  </Text>
                </View>
                <Preview conversation={item} />
              </View>
              {item.unread_count ? (
                <View
                  style={[styles.badge, { backgroundColor: theme.colors.primary }]}
                  testID={`conversation-unread-${item.id}`}
                >
                  <Text style={[theme.typography.caption, { color: theme.colors.onPrimary }]}>
                    {item.unread_count > 99 ? '99+' : item.unread_count}
                  </Text>
                </View>
              ) : null}
            </Pressable>
          );
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  top: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  badge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
