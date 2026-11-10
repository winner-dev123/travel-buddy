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
import { getGroup, groupKeys } from '@/features/groups/api';
import {
  deleteMessage,
  getConversation,
  isHidden,
  listMessages,
  listPins,
  markRead,
  messageKeys,
  muteConversation,
  pinMessage,
  POLL_CHAT_MS,
  sendMessage,
  unpinMessage,
  type Message,
  type MessageList,
} from '@/features/messages/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-081 Direct message thread (DM-001..013), refreshed by polling (ADR-0023). */
const MUTE_FOR = [
  { hours: 1, label: 'messages.muteFor.1' },
  { hours: 8, label: 'messages.muteFor.8' },
  { hours: 168, label: 'messages.muteFor.168' },
] as const;

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useSessionStore((state) => state.me?.account.id);
  const [draft, setDraft] = useState('');
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [showPins, setShowPins] = useState(false);
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

  const groupId = conversation.data?.group_id ?? null;
  const groupAccess = useQuery({
    queryKey: groupKeys.detail(groupId ?? ''),
    queryFn: () => getGroup(getApiClient(), groupId as string),
    enabled: groupId !== null,
  });
  // Direct chats: either member may pin. Groups: only with `messages.pin` (DM-011, GCHAT-005).
  const canPin =
    conversation.data?.kind === 'direct' ||
    (groupAccess.data?.my_membership?.permissions.includes('messages.pin') ?? false);
  const pins = useQuery({
    queryKey: messageKeys.pins(id),
    queryFn: () => listPins(getApiClient(), id),
    refetchInterval: POLL_CHAT_MS * 4,
  });
  const pin = useMutation({
    mutationFn: ({ message, on }: { message: Message; on: boolean }) =>
      on
        ? pinMessage(getApiClient(), id, message.id)
        : unpinMessage(getApiClient(), id, message.id),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.pins(id) });
      void queryClient.invalidateQueries({ queryKey: messageKeys.history(id) });
    },
  });

  const mute = useMutation({
    mutationFn: (hours: number | null) =>
      muteConversation(
        getApiClient(),
        id,
        hours === null ? null : new Date(Date.now() + hours * 3_600_000),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(messageKeys.conversation(id), updated);
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
    },
  });
  const mutedUntil = conversation.data?.muted_until ?? null;
  // Compared with the last fetch, not the render time (renders must stay pure).
  const muted = mutedUntil !== null && Date.parse(mutedUntil) > conversation.dataUpdatedAt;
  const chooseMute = () =>
    Alert.alert(t('messages.muteTitle'), t('messages.muteBody'), [
      ...MUTE_FOR.map(({ hours, label }) => ({
        text: t(label),
        onPress: () => mute.mutate(hours),
      })),
      { text: t('common.cancel'), style: 'cancel' as const },
    ]);

  const send = useMutation({
    mutationFn: (body: string) =>
      sendMessage(getApiClient(), id, pending.current, body, replyTo?.id),
    onSuccess: (message) => {
      setDraft('');
      setReplyTo(null);
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
    const common = [
      ...(conversation.data?.can_send
        ? [{ text: t('messages.reply'), onPress: () => setReplyTo(message) }]
        : []),
      ...(canPin
        ? [
            {
              text: message.pinned ? t('messages.unpin') : t('messages.pin'),
              onPress: () => pin.mutate({ message, on: !message.pinned }),
            },
          ]
        : []),
    ];
    if (message.sender?.id === me) {
      Alert.alert(t('messages.actions'), undefined, [
        ...common,
        { text: t('messages.delete'), style: 'destructive', onPress: () => remove.mutate(message) },
        { text: t('common.cancel'), style: 'cancel' },
      ]);
    } else {
      Alert.alert(t('messages.actions'), undefined, [
        ...common,
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
      ? {
          blocked: t('messages.blocked'),
          connection_required: t('messages.connectionRequired'),
          member_restricted: t('messages.memberRestricted'),
          chat_admins_only: t('messages.adminsOnly'),
          archived: t('messages.archived'),
        }[data.send_restriction ?? 'connection_required']
      : null;
  const pinned = pins.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: data?.title ?? data?.counterpart?.display_name ?? t('messages.chatTitle'),
        }}
      />
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        {data ? (
          <View style={[styles.muteBar, { borderBottomColor: theme.colors.divider }]}>
            {muted ? (
              <Text
                style={[
                  styles.fill,
                  theme.typography.caption,
                  { color: theme.colors.textSecondary },
                ]}
                testID="chat-muted"
              >
                {t('messages.mutedUntil', {
                  when: new Date(mutedUntil as string).toLocaleString(i18n.language, {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  }),
                })}
              </Text>
            ) : (
              <View style={styles.fill} />
            )}
            <Pressable
              onPress={() => (muted ? mute.mutate(null) : chooseMute())}
              accessibilityRole="button"
              accessibilityLabel={muted ? t('messages.unmute') : t('messages.mute')}
              hitSlop={8}
              testID="chat-mute"
            >
              <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                {muted ? `🔔 ${t('messages.unmute')}` : `🔕 ${t('messages.mute')}`}
              </Text>
            </Pressable>
          </View>
        ) : null}
        {mute.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        {pinned.length > 0 ? (
          <View
            style={[styles.pins, { borderBottomColor: theme.colors.divider }]}
            testID="chat-pins"
          >
            <Pressable
              onPress={() => setShowPins((open) => !open)}
              accessibilityRole="button"
              accessibilityState={{ expanded: showPins }}
              testID="chat-pins-toggle"
            >
              <Text
                numberOfLines={1}
                style={[theme.typography.label, { color: theme.colors.textPrimary }]}
              >
                {`📌 ${t('messages.pinnedCount', { count: pinned.length })} · ${pinned[0]?.body ?? ''}`}
              </Text>
            </Pressable>
            {showPins
              ? pinned.map((message) => (
                  <View key={message.id} style={styles.pinRow} testID={`pin-${message.id}`}>
                    <Text
                      style={[
                        styles.fill,
                        theme.typography.body,
                        { color: theme.colors.textPrimary },
                      ]}
                    >
                      {message.body}
                    </Text>
                    {canPin ? (
                      <Pressable
                        onPress={() => pin.mutate({ message, on: false })}
                        accessibilityRole="button"
                        testID={`unpin-${message.id}`}
                      >
                        <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                          {t('messages.unpin')}
                        </Text>
                      </Pressable>
                    ) : null}
                  </View>
                ))
              : null}
          </View>
        ) : null}
        {pin.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
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
            const group = data?.kind === 'group';
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
                {item.kind === 'announcement' ? (
                  <Text
                    style={[
                      theme.typography.caption,
                      { color: mine ? theme.colors.onPrimary : theme.colors.primary },
                    ]}
                    testID={`announcement-${item.id}`}
                  >
                    {t('messages.announcement')}
                  </Text>
                ) : null}
                {group && !mine ? (
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {item.sender?.display_name ?? t('messages.deletedUser')}
                  </Text>
                ) : null}
                {item.reply_to ? (
                  <Text
                    numberOfLines={1}
                    style={[
                      theme.typography.caption,
                      styles.quote,
                      { color: mine ? theme.colors.onPrimary : theme.colors.textSecondary },
                    ]}
                    testID={`reply-quote-${item.id}`}
                  >
                    {`↩ ${item.reply_to.deleted ? t('messages.deleted') : (item.reply_to.snippet ?? '')}`}
                  </Text>
                ) : null}
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
              {replyTo ? (
                <View style={styles.pinRow} testID="chat-replying">
                  <Text
                    numberOfLines={1}
                    style={[
                      styles.fill,
                      theme.typography.caption,
                      { color: theme.colors.textSecondary },
                    ]}
                  >
                    {t('messages.replyingTo', {
                      name: replyTo.sender?.display_name ?? t('messages.deletedUser'),
                      text: replyTo.body ?? '',
                    })}
                  </Text>
                  <Pressable
                    onPress={() => setReplyTo(null)}
                    accessibilityRole="button"
                    accessibilityLabel={t('messages.cancelReply')}
                    testID="chat-cancel-reply"
                  >
                    <Text style={[theme.typography.label, { color: theme.colors.primary }]}>✕</Text>
                  </Pressable>
                </View>
              ) : null}
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
  pins: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 6,
  },
  pinRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  muteBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  quote: { borderLeftWidth: 2, paddingLeft: 6, opacity: 0.9 },
});
