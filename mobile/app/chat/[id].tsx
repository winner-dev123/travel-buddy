import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiNetworkError, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { showActions } from '@/components/ActionSheet';
import { Notice } from '@/components/Form';
import { MediaPreview } from '@/features/feed/PhotoGallery';
import { Avatar } from '@/features/feed/PostCard';
import { getGroup, groupKeys } from '@/features/groups/api';
import {
  pickPhotos,
  takePhoto,
  UnsupportedPhotoError,
  uploadPhoto,
  type DraftPhoto,
} from '@/features/media/upload';
import {
  clearConversation,
  deleteMessage,
  getConversation,
  isHidden,
  listMessages,
  listPins,
  markRead,
  messageKeys,
  muteConversation,
  openGift,
  pinMessage,
  POLL_CHAT_MS,
  QUICK_REACTIONS,
  sendMessage,
  setMessageReaction,
  unpinMessage,
  type Conversation,
  type Message,
  type MessageList,
} from '@/features/messages/api';
import { ChatBackdrop } from '@/features/messages/ChatBackdrop';
import { Composer } from '@/features/messages/Composer';
import { ExpressionTray } from '@/features/messages/ExpressionTray';
import { GiftBubble } from '@/features/messages/GiftBubble';
import { giftNameKey, type GiftCode } from '@/features/messages/gifts';
import {
  discardMessage,
  enqueueMessage,
  retryMessage,
  sendQueuedMessages,
  useOutboxStore,
  type OutboxItem,
} from '@/features/messages/outbox';
import { TypingIndicator } from '@/features/messages/TypingIndicator';
import { realtimeHandle, reportTyping } from '@/features/realtime/handle';
import { useRealtimeStore } from '@/features/realtime/store';
import { useChatPreferences } from '@/state/chatPreferences';
import { fontFamilies } from '@/theme/tokens';
import { useAppTheme } from '@/theme/useAppTheme';

/**
 * SCR-081 Direct message thread (DM-001..013). Live over the realtime connection (ADR-0033) and
 * refreshed by polling when there isn't one (ADR-0023). Text messages and gifts go through the
 * outbox, so a message written without a network shows at once and is sent when a connection comes
 * back. The panel beside the field adds emoji and, in direct chats, sends gifts (DM-016).
 */
const MUTE_FOR = [
  { hours: 1, label: 'messages.muteFor.1' },
  { hours: 8, label: 'messages.muteFor.8' },
  { hours: 168, label: 'messages.muteFor.168' },
] as const;

/** With a live connection, polling is only a safety net (new messages arrive as frames). */
const LIVE_POLL_MS = 30_000;
/** "Typing" stops this long after the last keystroke. */
const TYPING_IDLE_MS = 5_000;

type Row = { kind: 'message'; message: Message } | { kind: 'queued'; item: OutboxItem };

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
  const live = useRealtimeStore((state) => state.status === 'online');
  const typingMap = useRealtimeStore((state) => state.typing[id]);
  const outbox = useOutboxStore((state) => state.items);
  const sendSide = useChatPreferences((state) => state.sendSide);
  const background = useChatPreferences((state) => state.background);
  const [trayOpen, setTrayOpen] = useState(false);

  const conversation = useQuery({
    queryKey: messageKeys.conversation(id),
    queryFn: () => getConversation(getApiClient(), id),
    refetchInterval: live ? LIVE_POLL_MS * 2 : POLL_CHAT_MS * 4,
  });
  const history = useQuery({
    queryKey: messageKeys.history(id),
    queryFn: () => listMessages(getApiClient(), id),
    refetchInterval: live ? LIVE_POLL_MS : POLL_CHAT_MS,
  });

  const newest = history.data?.page.newest_seq ?? 0;
  const readThrough = conversation.data?.read_through_seq ?? 0;
  useEffect(() => {
    if (newest <= readThrough) return;
    // Over the live connection the other side sees "Read" at once; REST otherwise.
    const socket = realtimeHandle.current;
    if (
      socket?.isOnline &&
      socket.send('receipt.read', { conversation_id: id, read_through_seq: newest })
    ) {
      queryClient.setQueryData<Conversation>(messageKeys.conversation(id), (old) =>
        old ? { ...old, read_through_seq: Math.max(old.read_through_seq, newest) } : old,
      );
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
      return;
    }
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
    refetchInterval: live ? LIVE_POLL_MS * 2 : POLL_CHAT_MS * 4,
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
    showActions(t('messages.muteTitle'), t('messages.muteBody'), [
      ...MUTE_FOR.map(({ hours, label }) => ({
        text: t(label),
        onPress: () => mute.mutate(hours),
      })),
      { text: t('common.cancel'), style: 'cancel' as const },
    ]);

  const react = useMutation({
    mutationFn: ({ message, emoji, on }: { message: Message; emoji: string; on: boolean }) =>
      setMessageReaction(getApiClient(), id, message.id, emoji, on),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: messageKeys.history(id) }),
  });
  const toggleReaction = (message: Message, emoji: string) => {
    const mine = message.reactions.some((r) => r.emoji === emoji && r.reacted_by_me);
    react.mutate({ message, emoji, on: !mine });
  };
  const chooseReaction = (message: Message) =>
    showActions(t('messages.react'), undefined, [
      ...QUICK_REACTIONS.map((emoji) => ({
        text: emoji,
        onPress: () => toggleReaction(message, emoji),
      })),
      { text: t('common.cancel'), style: 'cancel' as const },
    ]);
  const clear = useMutation({
    mutationFn: (throughSeq: number) => clearConversation(getApiClient(), id, throughSeq),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messageKeys.history(id) });
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
    },
  });
  const confirmClear = (throughSeq: number) =>
    Alert.alert(t('messages.clearTitle'), t('messages.clearBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('messages.clear'), style: 'destructive', onPress: () => clear.mutate(throughSeq) },
    ]);

  // DM-002: photos go to quarantine first and are scanned before anyone else sees them.
  const [photoNotice, setPhotoNotice] = useState<string | null>(null);
  // A poll that started before the send would overwrite the new bubble with an older list when it
  // lands, so in-flight polls are cancelled first; the next one includes the message anyway.
  const showSent = async (message: Message) => {
    await queryClient.cancelQueries({ queryKey: messageKeys.history(id) });
    queryClient.setQueryData<MessageList>(messageKeys.history(id), (old) =>
      old && !old.data.some((m) => m.id === message.id)
        ? {
            data: [...old.data, message],
            page: { ...old.page, newest_seq: Math.max(old.page.newest_seq ?? 0, message.seq) },
          }
        : old,
    );
  };
  const sendPhoto = useMutation({
    mutationFn: async (photo: DraftPhoto) => {
      const client = getApiClient();
      const mediaId = await uploadPhoto(client, photo, 'message');
      return sendMessage(client, id, pending.current, draft.trim(), replyTo?.id, [mediaId]);
    },
    onSuccess: (message) => {
      setDraft('');
      setReplyTo(null);
      pending.current = getApiClient().newIdempotencyKey();
      void showSent(message);
      void queryClient.invalidateQueries({ queryKey: messageKeys.inbox });
    },
  });
  const addPhoto = (source: 'library' | 'camera') => {
    setPhotoNotice(null);
    void (async () => {
      try {
        const picked = source === 'library' ? await pickPhotos(1) : await takePhoto();
        if (picked === 'denied') setPhotoNotice(t('compose.cameraDenied'));
        else if (picked[0]) sendPhoto.mutate(picked[0]);
      } catch (error) {
        setPhotoNotice(
          error instanceof UnsupportedPhotoError
            ? t('compose.photoUnsupported')
            : t('compose.photoFailed'),
        );
      }
    })();
  };
  const choosePhoto = () =>
    Alert.alert(t('messages.photoTitle'), undefined, [
      { text: t('compose.addPhotos'), onPress: () => addPhoto('library') },
      { text: t('compose.takePhoto'), onPress: () => addPhoto('camera') },
      { text: t('common.cancel'), style: 'cancel' },
    ]);

  // Typing: started while the draft has text, stopped when it's cleared, sent, idle or left.
  const typingIdle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const changeDraft = (text: string) => {
    setDraft(text);
    const typing = text.trim().length > 0;
    reportTyping(id, typing);
    if (typingIdle.current) clearTimeout(typingIdle.current);
    typingIdle.current = typing ? setTimeout(() => reportTyping(id, false), TYPING_IDLE_MS) : null;
  };
  useEffect(
    () => () => {
      if (typingIdle.current) clearTimeout(typingIdle.current);
      reportTyping(id, false);
    },
    [id],
  );

  // What a message says in a quote or the pinned bar (a gift by its name).
  const textOf = (message: Message) =>
    message.gift ? t(giftNameKey(message.gift.code)) : (message.body ?? '');
  const submit = () => {
    const body = draft.trim();
    if (!body) return;
    enqueueMessage({
      clientMessageId: pending.current,
      conversationId: id,
      body,
      replyTo: replyTo ? { id: replyTo.id, snippet: textOf(replyTo) } : null,
    });
    setDraft('');
    setReplyTo(null);
    pending.current = getApiClient().newIdempotencyKey();
    if (typingIdle.current) clearTimeout(typingIdle.current);
    reportTyping(id, false);
    void sendQueuedMessages(queryClient);
  };
  // DM-016: the emoji and gifts panel replaces the keyboard while it's open.
  const toggleTray = () => {
    if (!trayOpen) Keyboard.dismiss();
    setTrayOpen((open) => !open);
  };
  useEffect(() => {
    if (!trayOpen) return;
    const back = BackHandler.addEventListener('hardwareBackPress', () => {
      setTrayOpen(false);
      return true;
    });
    return () => back.remove();
  }, [trayOpen]);
  const addEmoji = (emoji: string) => changeDraft(`${draft}${emoji}`);
  const sendGift = (gift: GiftCode) => {
    enqueueMessage({
      clientMessageId: pending.current,
      conversationId: id,
      body: '',
      gift,
      replyTo: replyTo ? { id: replyTo.id, snippet: textOf(replyTo) } : null,
    });
    setReplyTo(null);
    setTrayOpen(false);
    pending.current = getApiClient().newIdempotencyKey();
    void sendQueuedMessages(queryClient);
  };
  // Opening shows at once; the server's answer replaces the guess, a failure puts the bow back.
  const patchGift = (messageId: string, openedAt: string | null) =>
    queryClient.setQueryData<MessageList>(messageKeys.history(id), (old) =>
      old
        ? {
            ...old,
            data: old.data.map((m) =>
              m.id === messageId && m.gift ? { ...m, gift: { ...m.gift, opened_at: openedAt } } : m,
            ),
          }
        : old,
    );
  const unwrap = useMutation({
    mutationFn: (message: Message) => openGift(getApiClient(), id, message.id),
    // A dropped connection is worth another try; a refusal isn't.
    retry: (failures, error) => error instanceof ApiNetworkError && failures < 2,
    onMutate: async (message) => {
      await queryClient.cancelQueries({ queryKey: messageKeys.history(id) });
      patchGift(message.id, new Date().toISOString());
    },
    onSuccess: (updated) => patchGift(updated.id, updated.gift?.opened_at ?? null),
    onError: (_error, message) => patchGift(message.id, null),
  });

  const queuedActions = (item: OutboxItem) =>
    showActions(t('messages.notSent'), undefined, [
      {
        text: t('messages.retry'),
        onPress: () => {
          retryMessage(item.clientMessageId);
          void sendQueuedMessages(queryClient);
        },
      },
      {
        text: t('messages.discard'),
        style: 'destructive',
        onPress: () => discardMessage(item.clientMessageId),
      },
      { text: t('common.cancel'), style: 'cancel' },
    ]);
  const remove = useMutation({
    mutationFn: (message: Message) => deleteMessage(getApiClient(), id, message.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: messageKeys.history(id) }),
  });

  // SCR-083: group chats have reply threads (a reply can't start another thread).
  const threaded = conversation.data !== undefined && conversation.data.kind !== 'direct';
  const openThread = (message: Message) =>
    router.push({ pathname: '/chat/thread', params: { id, root: message.id } });

  const actions = (message: Message) => {
    if (isHidden(message)) return;
    const common = [
      { text: t('messages.react'), onPress: () => chooseReaction(message) },
      ...(conversation.data?.can_send
        ? [{ text: t('messages.reply'), onPress: () => setReplyTo(message) }]
        : []),
      ...(threaded && !message.thread_root_id
        ? [{ text: t('messages.replyInThread'), onPress: () => openThread(message) }]
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
      showActions(t('messages.actions'), undefined, [
        ...common,
        { text: t('messages.delete'), style: 'destructive', onPress: () => remove.mutate(message) },
        { text: t('common.cancel'), style: 'cancel' },
      ]);
    } else {
      showActions(t('messages.actions'), undefined, [
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
  const persisted = history.data?.data ?? [];
  // Messages still in the outbox show after the persisted ones until the server has them.
  const known = new Set(persisted.map((m) => m.client_message_id).filter(Boolean));
  const queued = outbox.filter((i) => i.conversationId === id && !known.has(i.clientMessageId));
  const rows: Row[] = [
    ...queued.map((item): Row => ({ kind: 'queued', item })).reverse(),
    ...[...persisted].reverse().map((message): Row => ({ kind: 'message', message })),
  ]; // inverted list: newest first
  const failed = queued.filter((i) => i.status === 'failed').at(-1);
  const peerRead = data?.peer_read_through_seq ?? null;
  const lastMine = persisted.filter((m) => m.sender?.id === me).at(-1);
  const direct = data?.kind === 'direct';
  const nameOf = (userId: string) =>
    (data?.counterpart?.id === userId ? data.counterpart.display_name : null) ??
    persisted.find((m) => m.sender?.id === userId)?.sender?.display_name ??
    t('messages.someone');
  const typingNames = Object.keys(typingMap ?? {})
    .filter((userId) => userId !== me)
    .map(nameOf);
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
          headerRight: () => (
            <Pressable
              onPress={() => router.push('/settings/chat')}
              accessibilityRole="button"
              accessibilityLabel={t('chatSettings.title')}
              hitSlop={10}
              testID="chat-settings"
            >
              <Ionicons name="color-palette-outline" size={22} color={theme.colors.textPrimary} />
            </Pressable>
          ),
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
            {newest > 0 ? (
              <Pressable
                onPress={() => confirmClear(newest)}
                accessibilityRole="button"
                hitSlop={8}
                testID="chat-clear"
              >
                <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
                  {t('messages.clear')}
                </Text>
              </Pressable>
            ) : null}
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
                {`📌 ${t('messages.pinnedCount', { count: pinned.length })} · ${pinned[0] ? textOf(pinned[0]) : ''}`}
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
                      {textOf(message)}
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
        <View style={[styles.fill, styles.clip]}>
          <ChatBackdrop background={background} />
          <FlatList<Row>
            inverted
            data={rows}
            keyExtractor={(row) =>
              row.kind === 'queued' ? `queued-${row.item.clientMessageId}` : row.message.id
            }
            contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}
            ListHeaderComponent={<TypingIndicator names={typingNames} />}
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
            renderItem={({ item: row }) => {
              if (row.kind === 'queued') {
                const queuedItem = row.item;
                const isFailed = queuedItem.status === 'failed';
                const queuedStatus = (
                  <View
                    style={styles.status}
                    testID={`queued-status-${queuedItem.clientMessageId}`}
                  >
                    <Ionicons
                      name={isFailed ? 'alert-circle' : 'time-outline'}
                      size={13}
                      color={isFailed ? theme.colors.danger : theme.colors.textSecondary}
                    />
                    <Text
                      style={[
                        theme.typography.caption,
                        { color: isFailed ? theme.colors.danger : theme.colors.textSecondary },
                      ]}
                    >
                      {isFailed ? t('messages.notSentTap') : t('messages.sending')}
                    </Text>
                  </View>
                );
                if (queuedItem.gift) {
                  return (
                    <View style={styles.mineColumn}>
                      <GiftBubble
                        gift={{ code: queuedItem.gift, opened_at: null }}
                        mine
                        senderName=""
                        onPress={isFailed ? () => queuedActions(queuedItem) : undefined}
                        onLongPress={() => queuedActions(queuedItem)}
                        testID={`queued-${queuedItem.clientMessageId}`}
                      />
                      {queuedStatus}
                    </View>
                  );
                }
                return (
                  <View style={styles.mineColumn}>
                    <Pressable
                      onPress={isFailed ? () => queuedActions(queuedItem) : undefined}
                      onLongPress={() => queuedActions(queuedItem)}
                      accessibilityHint={t('messages.actionsHint')}
                      style={[
                        styles.bubble,
                        styles.mine,
                        {
                          backgroundColor: isFailed ? theme.colors.surface : theme.colors.primary,
                          borderColor: isFailed ? theme.colors.danger : 'transparent',
                          borderWidth: isFailed ? 1 : 0,
                          opacity: isFailed ? 1 : 0.8,
                        },
                      ]}
                      testID={`queued-${queuedItem.clientMessageId}`}
                    >
                      {queuedItem.replyTo ? (
                        <Text
                          numberOfLines={1}
                          style={[
                            theme.typography.caption,
                            styles.quote,
                            {
                              color: isFailed ? theme.colors.textSecondary : theme.colors.onPrimary,
                            },
                          ]}
                        >
                          {`↩ ${queuedItem.replyTo.snippet ?? ''}`}
                        </Text>
                      ) : null}
                      <Text
                        style={[
                          theme.typography.body,
                          { color: isFailed ? theme.colors.textPrimary : theme.colors.onPrimary },
                        ]}
                      >
                        {queuedItem.body}
                      </Text>
                    </Pressable>
                    {queuedStatus}
                  </View>
                );
              }
              const item = row.message;
              const mine = item.sender?.id === me;
              const hidden = isHidden(item);
              const group = data?.kind === 'group';
              const isLastMine = mine && item.id === lastMine?.id;
              const read = isLastMine && peerRead !== null && peerRead >= item.seq;
              const gift = !hidden ? item.gift : null;
              const bubble = gift ? (
                <GiftBubble
                  gift={gift}
                  mine={mine}
                  senderName={item.sender?.display_name ?? t('messages.someone')}
                  onOpen={() => unwrap.mutate(item)}
                  opening={unwrap.isPending && unwrap.variables?.id === item.id}
                  onLongPress={() => actions(item)}
                  testID={`message-${item.id}`}
                />
              ) : (
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
                      {`↩ ${
                        item.reply_to.deleted
                          ? t('messages.deleted')
                          : item.reply_to.kind === 'gift' && !item.reply_to.snippet
                            ? t('messages.giftPreview')
                            : (item.reply_to.snippet ?? '')
                      }`}
                    </Text>
                  ) : null}
                  {!hidden && item.attachments.length > 0 ? (
                    <View style={styles.attachments} testID={`message-photos-${item.id}`}>
                      {item.attachments.map((media) => (
                        <MediaPreview key={media.id} media={media} />
                      ))}
                    </View>
                  ) : null}
                  {hidden || item.body ? (
                    <Text
                      style={[
                        theme.typography.body,
                        {
                          color: mine ? theme.colors.onPrimary : theme.colors.textPrimary,
                          fontStyle: hidden ? 'italic' : 'normal',
                        },
                      ]}
                    >
                      {hidden ? t('messages.deleted') : item.body}
                    </Text>
                  ) : null}
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
                  {threaded && (item.thread_reply_count ?? 0) > 0 ? (
                    <Pressable
                      onPress={() => openThread(item)}
                      accessibilityRole="link"
                      hitSlop={6}
                      testID={`thread-link-${item.id}`}
                    >
                      <Text
                        style={[
                          theme.typography.caption,
                          styles.threadLink,
                          { color: mine ? theme.colors.onPrimary : theme.colors.primary },
                        ]}
                      >
                        {t('messages.threadReplies', { count: item.thread_reply_count ?? 0 })}
                      </Text>
                    </Pressable>
                  ) : null}
                  {item.reactions.length > 0 && !hidden ? (
                    <View style={styles.reactions}>
                      {item.reactions.map((reaction) => (
                        <Pressable
                          key={reaction.emoji}
                          onPress={() => toggleReaction(item, reaction.emoji)}
                          accessibilityRole="button"
                          accessibilityState={{ selected: reaction.reacted_by_me }}
                          accessibilityLabel={t('messages.reactionA11y', {
                            emoji: reaction.emoji,
                            count: reaction.count,
                          })}
                          style={[
                            styles.reaction,
                            {
                              borderColor: reaction.reacted_by_me
                                ? theme.colors.onPrimary
                                : theme.colors.divider,
                            },
                          ]}
                          testID={`reaction-${item.id}-${reaction.emoji}`}
                        >
                          <Text
                            style={[
                              theme.typography.caption,
                              { color: mine ? theme.colors.onPrimary : theme.colors.textPrimary },
                            ]}
                          >
                            {`${reaction.emoji} ${reaction.count}`}
                          </Text>
                        </Pressable>
                      ))}
                    </View>
                  ) : null}
                </Pressable>
              );
              // My gifts say whether the other person has opened them yet (DM-016).
              const giftStatus =
                mine && gift ? (
                  <View style={styles.status} testID={`gift-status-${item.id}`}>
                    <Ionicons
                      name={gift.opened_at ? 'gift' : 'gift-outline'}
                      size={13}
                      color={gift.opened_at ? theme.colors.primary : theme.colors.textSecondary}
                    />
                    <Text
                      style={[
                        theme.typography.caption,
                        {
                          color: gift.opened_at ? theme.colors.primary : theme.colors.textSecondary,
                        },
                      ]}
                    >
                      {gift.opened_at ? t('messages.giftOpened') : t('messages.giftNotOpened')}
                    </Text>
                  </View>
                ) : null;
              if (!isLastMine) {
                return giftStatus ? (
                  <View style={styles.mineColumn}>
                    {bubble}
                    {giftStatus}
                  </View>
                ) : (
                  bubble
                );
              }
              // My newest message: "Sent", then the reader's face and "Read" once they've seen it.
              const reader = direct ? (data?.counterpart ?? null) : null;
              return (
                <View style={styles.mineColumn}>
                  {bubble}
                  {giftStatus}
                  {read ? (
                    <View
                      style={styles.status}
                      accessible
                      accessibilityLabel={
                        reader
                          ? t('messages.readBy', { name: reader.display_name })
                          : t('messages.read')
                      }
                      testID="message-read"
                    >
                      {reader ? <Avatar user={reader} size={16} /> : null}
                      <Text
                        style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                      >
                        {t('messages.read')}
                      </Text>
                    </View>
                  ) : (
                    <View style={styles.status} testID="message-sent">
                      <Ionicons name="checkmark" size={13} color={theme.colors.textSecondary} />
                      <Text
                        style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                      >
                        {t('messages.sent')}
                      </Text>
                    </View>
                  )}
                </View>
              );
            }}
          />
        </View>
        <View
          style={[
            styles.composer,
            {
              borderTopColor: theme.colors.divider,
              backgroundColor: theme.colors.background,
              padding: theme.spacing[3],
            },
          ]}
        >
          {restriction ? (
            <Notice tone="info" testID="chat-restricted">
              {restriction}
            </Notice>
          ) : (
            <>
              {failed ? (
                <Notice tone="error" testID="chat-send-error">
                  {failed.reason === 'filtered'
                    ? t('messages.filtered')
                    : t('messages.notSentHint')}
                </Notice>
              ) : null}
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
                      text: textOf(replyTo),
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
              {photoNotice ? (
                <Notice tone="info" testID="chat-photo-notice">
                  {photoNotice}
                </Notice>
              ) : null}
              {sendPhoto.isError ? <Notice tone="error">{t('compose.uploadFailed')}</Notice> : null}
              {unwrap.isError ? (
                <Notice tone="error" testID="gift-open-failed">
                  {t('messages.giftOpenFailed')}
                </Notice>
              ) : null}
              <Composer
                value={draft}
                onChangeText={changeDraft}
                onSend={submit}
                onPhoto={choosePhoto}
                photoBusy={sendPhoto.isPending}
                sendSide={sendSide}
                onToggleTray={toggleTray}
                trayOpen={trayOpen}
                onFocusField={() => setTrayOpen(false)}
              />
            </>
          )}
        </View>
        {trayOpen && !restriction ? (
          <ExpressionTray onEmoji={addEmoji} onGift={direct ? sendGift : null} />
        ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  clip: { overflow: 'hidden' },
  center: { textAlign: 'center' },
  bubble: { maxWidth: '80%', borderRadius: 16, paddingHorizontal: 12, paddingVertical: 8, gap: 2 },
  mine: { alignSelf: 'flex-end' },
  theirs: { alignSelf: 'flex-start' },
  mineColumn: { alignItems: 'flex-end', gap: 3 },
  status: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 4 },
  composer: { borderTopWidth: StyleSheet.hairlineWidth, gap: 8 },
  pins: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 6,
  },
  pinRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  reactions: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: 4 },
  attachments: { gap: 4, width: 220 },
  threadLink: { fontFamily: fontFamilies.semibold, marginTop: 4 },
  reaction: { borderWidth: 1, borderRadius: 12, paddingHorizontal: 6, paddingVertical: 1 },
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
