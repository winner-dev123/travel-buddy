import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, TextField } from '@/components/Form';
import {
  deleteMessage,
  getConversation,
  isHidden,
  listMessages,
  markRead,
  messageKeys,
  POLL_CHAT_MS,
  sendMessage,
  type Message,
  type MessageList,
} from '@/features/messages/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-081 Direct message thread (DM-001..013), refreshed by polling (ADR-0023). */
export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useSessionStore((state) => state.me?.account.id);
  const [draft, setDraft] = useState('');
  // One client_message_id per message the user writes; a retry of that message reuses it, so a
  // send that reached the server before the connection dropped is never duplicated (DM-005).
  const pending = useRef<string>(getApiClient().newIdempotencyKey());

  const conversation = useQuery({
    queryKey: messageKeys.conversation(id),
    queryFn: () => getConversation(getApiClient(), id),
    refetchInterval: POLL_CHAT_MS * 4,
  });
  const history = useQuery({
    queryKey: messageKeys.history(id),
    queryFn: () => listMessages(getApiClient(), id),
    refetchInterval: POLL_CHAT_MS,
  });

  const newest = history.data?.page.newest_seq ?? 0;
  const readThrough = conversation.data?.read_through_seq ?? 0;
  useEffect(() => {
    if (newest <= readThrough) return;
    void markRead(getApiClient(), id, newest)
      .then(() => {
        void queryClient.invalidateQueries({ queryKey: messageKeys.conversation(id) });
        void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
      })
      .catch(() => undefined); // retried on the next refresh
  }, [id, newest, readThrough, queryClient]);

  const send = useMutation({
    mutationFn: (body: string) => sendMessage(getApiClient(), id, pending.current, body),
    onSuccess: (message) => {
      setDraft('');
      pending.current = getApiClient().newIdempotencyKey();
      queryClient.setQueryData<MessageList>(messageKeys.history(id), (old) =>
        old && !old.data.some((m) => m.id === message.id)
          ? {
              data: [...old.data, message],
              page: { ...old.page, newest_seq: Math.max(old.page.newest_seq ?? 0, message.seq) },
            }
          : old,
      );
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
    },
  });
  const remove = useMutation({
    mutationFn: (message: Message) => deleteMessage(getApiClient(), id, message.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: messageKeys.history(id) }),
  });

  const actions = (message: Message) => {
    if (isHidden(message)) return;
    if (message.sender?.id === me) {
      Alert.alert(t('messages.actions'), undefined, [
        { text: t('messages.delete'), style: 'destructive', onPress: () => remove.mutate(message) },
        { text: t('common.cancel'), style: 'cancel' },
      ]);
    } else {
      Alert.alert(t('messages.actions'), undefined, [
        {
          text: t('messages.report'),
          onPress: () =>
            router.push({
              pathname: '/report',
              params: {
                type: 'message',
                target: message.id,
                name: message.sender?.display_name ?? '',
              },
            }),
        },
        { text: t('common.cancel'), style: 'cancel' },
      ]);
    }
  };

  const data = conversation.data;
  const messages = [...(history.data?.data ?? [])].reverse(); // inverted list: newest first
  const peerRead = data?.peer_read_through_seq ?? null;
  const lastMine = (history.data?.data ?? []).filter((m) => m.sender?.id === me).at(-1);
  const restriction =
    data && !data.can_send
      ? data.send_restriction === 'blocked'
        ? t('messages.blocked')
        : t('messages.connectionRequired')
      : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: data?.counterpart?.display_name ?? t('messages.chatTitle'),
        }}
      />
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <FlatList<Message>
          inverted
          data={messages}
          keyExtractor={(message) => message.id}
          contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
          ListFooterComponent={
            <Text
              style={[
                theme.typography.caption,
                styles.center,
                { color: theme.colors.textSecondary },
              ]}
            >
              {t('messages.notEncrypted')}
            </Text>
          }
          ListEmptyComponent={
            history.isPending ? (
              <ActivityIndicator color={theme.colors.primary} />
            ) : history.isError ? (
              <Notice tone="error">{t('messages.loadFailed')}</Notice>
            ) : (
              <Text
                style={[
                  theme.typography.body,
                  styles.center,
                  { color: theme.colors.textSecondary },
                ]}
              >
                {t('messages.noMessages')}
              </Text>
            )
          }
          renderItem={({ item }) => {
            const mine = item.sender?.id === me;
            const hidden = isHidden(item);
            return (
              <Pressable
                onLongPress={() => actions(item)}
                accessibilityHint={t('messages.actionsHint')}
                style={[
                  styles.bubble,
                  mine ? styles.mine : styles.theirs,
                  { backgroundColor: mine ? theme.colors.primary : theme.colors.surface },
                ]}
                testID={`message-${item.id}`}
              >
                <Text
                  style={[
                    theme.typography.body,
                    {
                      color: mine ? theme.colors.onPrimary : theme.colors.textPrimary,
                      fontStyle: hidden ? 'italic' : 'normal',
                    },
                  ]}
                >
                  {hidden
                    ? t('messages.deleted')
                    : (item.body ?? (item.attachments.length ? t('messages.photo') : ''))}
                </Text>
                {item.edited_at && !hidden ? (
                  <Text
                    style={[
                      theme.typography.caption,
                      { color: mine ? theme.colors.onPrimary : theme.colors.textSecondary },
                    ]}
                  >
                    {t('messages.edited')}
                  </Text>
                ) : null}
                {mine && item.id === lastMine?.id && peerRead !== null && peerRead >= item.seq ? (
                  <Text
                    style={[theme.typography.caption, { color: theme.colors.onPrimary }]}
                    testID="message-read"
                  >
                    {t('messages.read')}
                  </Text>
                ) : null}
              </Pressable>
            );
          }}
        />
        <View
          style={[
            styles.composer,
            { borderTopColor: theme.colors.divider, padding: theme.spacing[3] },
          ]}
        >
          {restriction ? (
            <Notice tone="info" testID="chat-restricted">
              {restriction}
            </Notice>
          ) : (
            <>
              {send.isError ? <Notice tone="error">{t('messages.sendFailed')}</Notice> : null}
              <TextField
                label={t('messages.placeholder')}
                value={draft}
                onChangeText={setDraft}
                maxLength={4000}
                multiline
                testID="chat-input"
              />
              <Button
                label={t('messages.send')}
                onPress={() => send.mutate(draft.trim())}
                disabled={draft.trim().length === 0}
                busy={send.isPending}
                testID="chat-send"
              />
            </>
          )}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { textAlign: 'center' },
  bubble: { maxWidth: '80%', borderRadius: 16, paddingHorizontal: 12, paddingVertical: 8, gap: 2 },
  mine: { alignSelf: 'flex-end' },
  theirs: { alignSelf: 'flex-start' },
  composer: { borderTopWidth: StyleSheet.hairlineWidth, gap: 8 },
});
