import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FlatList, KeyboardAvoidingView, Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, TextField } from '@/components/Form';
import {
  getConversation,
  isHidden,
  listThread,
  messageKeys,
  POLL_CHAT_MS,
  sendThreadReply,
  type Message,
  type MessageList,
} from '@/features/messages/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-083 Reply thread in a group chat (GCHAT-002, GCHAT-004), refreshed by polling. */
export default function ThreadScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const { id, root } = useLocalSearchParams<{ id: string; root: string }>();
  const me = useSessionStore((state) => state.me?.account.id);
  const [draft, setDraft] = useState('');
  const pending = useRef(getApiClient().newIdempotencyKey());

  const conversation = useQuery({
    queryKey: messageKeys.conversation(id),
    queryFn: () => getConversation(getApiClient(), id),
  });
  const replies = useQuery({
    queryKey: messageKeys.thread(id, root),
    queryFn: () => listThread(getApiClient(), id, root),
    refetchInterval: POLL_CHAT_MS,
  });
  // The thread's first message, from the chat already loaded (older ones are shown without it).
  const rootMessage = queryClient
    .getQueryData<MessageList>(messageKeys.history(id))
    ?.data.find((m) => m.id === root);

  const send = useMutation({
    mutationFn: (body: string) => sendThreadReply(getApiClient(), id, pending.current, root, body),
    onSuccess: (message) => {
      setDraft('');
      pending.current = getApiClient().newIdempotencyKey();
      queryClient.setQueryData<MessageList>(messageKeys.thread(id, root), (old) =>
        old && !old.data.some((m) => m.id === message.id)
          ? { ...old, data: [...old.data, message] }
          : old,
      );
      void queryClient.invalidateQueries({ queryKey: messageKeys.history(id), exact: true });
    },
  });

  const bubble = (message: Message, isRoot = false) => {
    const hidden = isHidden(message);
    const mine = message.sender?.id === me;
    return (
      <View
        style={[
          styles.bubble,
          {
            backgroundColor: isRoot
              ? theme.colors.surface
              : mine
                ? theme.colors.primary
                : theme.colors.surface,
            borderColor: theme.colors.divider,
            alignSelf: isRoot ? 'stretch' : mine ? 'flex-end' : 'flex-start',
          },
        ]}
        testID={isRoot ? 'thread-root' : `thread-reply-${message.id}`}
      >
        <Text
          style={[
            theme.typography.caption,
            { color: mine && !isRoot ? theme.colors.onPrimary : theme.colors.textSecondary },
          ]}
        >
          {message.sender?.display_name ?? t('messages.deletedUser')}
        </Text>
        <Text
          style={[
            theme.typography.body,
            {
              color: mine && !isRoot ? theme.colors.onPrimary : theme.colors.textPrimary,
              fontStyle: hidden ? 'italic' : 'normal',
            },
          ]}
        >
          {hidden ? t('messages.deleted') : (message.body ?? t('messages.photo'))}
        </Text>
      </View>
    );
  };

  const data = replies.data?.data ?? [];
  const canSend = conversation.data?.can_send ?? false;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('messages.threadTitle') }} />
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <FlatList
          data={data}
          keyExtractor={(item) => item.id}
          contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
          ListHeaderComponent={
            rootMessage ? (
              bubble(rootMessage, true)
            ) : (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('messages.threadRootMissing')}
              </Text>
            )
          }
          ListEmptyComponent={
            replies.isSuccess ? (
              <Text
                style={[theme.typography.body, { color: theme.colors.textSecondary }]}
                testID="thread-empty"
              >
                {t('messages.threadEmpty')}
              </Text>
            ) : undefined
          }
          renderItem={({ item }) => bubble(item)}
          testID="thread-list"
        />
        {canSend ? (
          <View
            style={[
              styles.composer,
              { borderTopColor: theme.colors.divider, padding: theme.spacing[3] },
            ]}
          >
            {send.isError ? <Notice tone="error">{t('messages.sendFailed')}</Notice> : null}
            <TextField
              label={t('messages.threadInput')}
              value={draft}
              onChangeText={setDraft}
              multiline
              maxLength={4000}
              testID="thread-input"
            />
            <Button
              label={t('messages.send')}
              onPress={() => send.mutate(draft.trim())}
              disabled={draft.trim().length === 0}
              busy={send.isPending}
              testID="thread-send"
            />
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  bubble: { borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, padding: 10, maxWidth: '85%' },
  composer: { borderTopWidth: StyleSheet.hairlineWidth, gap: 8 },
});
