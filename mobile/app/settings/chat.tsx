import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useState, type ComponentProps } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type ImageSourcePropType,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Notice } from '@/components/Form';
import { accountKeys, fetchUserPosts } from '@/features/account/api';
import type { MediaRef } from '@/features/feed/types';
import { ChatBackdrop } from '@/features/messages/ChatBackdrop';
import {
  applyTripPhotoBackground,
  BUILTIN_BACKGROUND_IDS,
  BUILTIN_BACKGROUNDS,
  saveChatPreferences,
  useChatPreferences,
  type ChatBackground,
  type SendSide,
} from '@/state/chatPreferences';
import { useAppTheme } from '@/theme/useAppTheme';

type IoniconName = ComponentProps<typeof Ionicons>['name'];

const SIDES: { value: SendSide; icon: IoniconName }[] = [
  { value: 'right', icon: 'hand-right-outline' },
  { value: 'left', icon: 'hand-left-outline' },
];

/** Photos from the traveller's own stories that can become a background. */
function tripPhotos(media: MediaRef[]): (MediaRef & { url: string })[] {
  const seen = new Set<string>();
  return media.filter((m): m is MediaRef & { url: string } => {
    if (m.kind !== 'image' || m.status !== 'ready' || !m.url || seen.has(m.id)) return false;
    seen.add(m.id);
    return true;
  });
}

function sameBackground(a: ChatBackground, b: ChatBackground): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === 'builtin' && b.kind === 'builtin') return a.id === b.id;
  if (a.kind === 'photo' && b.kind === 'photo') return a.mediaId === b.mediaId;
  return true;
}

/**
 * SCR-119 Chat settings: the side of the send button (left for left-handed use) and the chat
 * background — none, one of the built-in trip photos, or a photo from the traveller's own
 * stories. Kept on this phone; a chosen photo is copied into the app so chats show it offline.
 */
export default function ChatSettingsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const me = useSessionStore((state) => state.me?.account.id);
  const sendSide = useChatPreferences((state) => state.sendSide);
  const background = useChatPreferences((state) => state.background);
  const [applying, setApplying] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const posts = useQuery({
    queryKey: accountKeys.posts(me ?? ''),
    queryFn: () => fetchUserPosts(getApiClient(), me as string),
    enabled: Boolean(me),
  });
  const photos = tripPhotos((posts.data?.data ?? []).flatMap((post) => post.media));

  const current = () => {
    const state = useChatPreferences.getState();
    return { sendSide: state.sendSide, background: state.background };
  };
  const choose = (next: ChatBackground) => {
    setFailed(false);
    saveChatPreferences({ ...current(), background: next });
  };
  const choosePhoto = (photo: MediaRef & { url: string }) => {
    setFailed(false);
    setApplying(photo.id);
    applyTripPhotoBackground(photo.id, photo.url, current())
      .catch(() => setFailed(true))
      .finally(() => setApplying(null));
  };

  const tile = (
    key: string,
    label: string,
    selected: boolean,
    onPress: () => void,
    source: ImageSourcePropType | null,
    busy = false,
  ) => (
    <Pressable
      key={key}
      onPress={onPress}
      disabled={busy}
      accessibilityRole="radio"
      accessibilityLabel={label}
      accessibilityState={{ selected, busy }}
      style={[
        styles.tile,
        {
          borderColor: selected ? theme.colors.primary : theme.colors.divider,
          borderWidth: selected ? 2 : StyleSheet.hairlineWidth,
          backgroundColor: theme.colors.surface,
        },
      ]}
      testID={`chat-bg-${key}`}
    >
      {source ? (
        <Image source={source} style={styles.tileImage} resizeMode="cover" />
      ) : (
        <View style={[styles.tileImage, styles.center]}>
          <Ionicons name="remove-circle-outline" size={26} color={theme.colors.textSecondary} />
        </View>
      )}
      <View style={[styles.tileLabel, { backgroundColor: theme.colors.surface }]}>
        <Text
          numberOfLines={1}
          style={[theme.typography.caption, { color: theme.colors.textPrimary }]}
        >
          {label}
        </Text>
        {busy ? <ActivityIndicator size="small" color={theme.colors.primary} /> : null}
        {selected && !busy ? (
          <Ionicons name="checkmark-circle" size={16} color={theme.colors.primary} />
        ) : null}
      </View>
    </Pressable>
  );

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('chatSettings.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[4] }}>
        {/* Preview: what a chat looks like with these choices. */}
        <View
          style={[styles.preview, { borderColor: theme.colors.divider }]}
          accessibilityLabel={t('chatSettings.preview')}
          testID="chat-settings-preview"
        >
          <View style={[StyleSheet.absoluteFill, { backgroundColor: theme.colors.background }]} />
          <ChatBackdrop background={background} testID="chat-settings-preview-background" />
          <View style={styles.previewBody}>
            <View style={[styles.bubble, styles.theirs, { backgroundColor: theme.colors.surface }]}>
              <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                {t('chatSettings.sampleTheirs')}
              </Text>
            </View>
            <View style={[styles.bubble, styles.mine, { backgroundColor: theme.colors.primary }]}>
              <Text style={[theme.typography.body, { color: theme.colors.onPrimary }]}>
                {t('chatSettings.sampleMine')}
              </Text>
            </View>
          </View>
          <View
            style={[
              styles.previewComposer,
              { flexDirection: sendSide === 'right' ? 'row' : 'row-reverse' },
            ]}
            testID={`chat-settings-preview-${sendSide}`}
          >
            <Ionicons name="camera-outline" size={18} color={theme.colors.primary} />
            <View
              style={[
                styles.previewField,
                { backgroundColor: theme.colors.surface, borderColor: theme.colors.borderStrong },
              ]}
            >
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('messages.placeholder')}
              </Text>
            </View>
            <View style={[styles.previewSend, { backgroundColor: theme.colors.primary }]}>
              <Ionicons name="send" size={12} color={theme.colors.onPrimary} />
            </View>
          </View>
        </View>

        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('chatSettings.sendSide')}
        </Text>
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel={t('chatSettings.sendSide')}
          style={[
            styles.card,
            { backgroundColor: theme.colors.surface, borderColor: theme.colors.divider },
          ]}
        >
          {SIDES.map(({ value, icon }, index) => {
            const selected = sendSide === value;
            return (
              <Pressable
                key={value}
                onPress={() => saveChatPreferences({ ...current(), sendSide: value })}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                style={({ pressed }) => [
                  styles.row,
                  {
                    minHeight: theme.minTouchTarget,
                    padding: theme.spacing[4],
                    gap: theme.spacing[3],
                    backgroundColor: pressed ? theme.colors.surfaceRaised : 'transparent',
                    borderTopColor: theme.colors.divider,
                    borderTopWidth: index === 0 ? 0 : StyleSheet.hairlineWidth,
                  },
                ]}
                testID={`chat-send-side-${value}`}
              >
                <View style={[styles.well, { backgroundColor: theme.colors.primaryMuted }]}>
                  <Ionicons name={icon} size={18} color={theme.colors.onPrimaryMuted} />
                </View>
                <View style={styles.text}>
                  <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                    {t(`chatSettings.sides.${value}`)}
                  </Text>
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {t(`chatSettings.sideDescriptions.${value}`)}
                  </Text>
                </View>
                <Ionicons
                  name={selected ? 'radio-button-on' : 'radio-button-off'}
                  size={22}
                  color={selected ? theme.colors.primary : theme.colors.textSecondary}
                />
              </Pressable>
            );
          })}
        </View>

        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('chatSettings.background')}
        </Text>
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel={t('chatSettings.background')}
          style={styles.grid}
        >
          {tile(
            'none',
            t('chatSettings.backgrounds.none'),
            background.kind === 'none',
            () => choose({ kind: 'none' }),
            null,
          )}
          {BUILTIN_BACKGROUND_IDS.map((id) =>
            tile(
              id,
              t(`chatSettings.backgrounds.${id}`),
              sameBackground(background, { kind: 'builtin', id }),
              () => choose({ kind: 'builtin', id }),
              BUILTIN_BACKGROUNDS[id],
            ),
          )}
        </View>

        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('chatSettings.yourPhotos')}
        </Text>
        {failed ? (
          <Notice tone="error" testID="chat-bg-failed">
            {t('chatSettings.photoFailed')}
          </Notice>
        ) : null}
        {posts.isPending && me ? (
          <ActivityIndicator color={theme.colors.primary} />
        ) : photos.length === 0 ? (
          <Text
            style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
            testID="chat-bg-no-photos"
          >
            {t('chatSettings.noPhotos')}
          </Text>
        ) : (
          <View accessibilityRole="radiogroup" style={styles.grid} testID="chat-bg-photos">
            {photos.map((photo, index) =>
              tile(
                `photo-${photo.id}`,
                photo.alt_text || t('chatSettings.photoLabel', { number: index + 1 }),
                background.kind === 'photo' && background.mediaId === photo.id,
                () => choosePhoto(photo),
                { uri: photo.url },
                applying === photo.id,
              ),
            )}
          </View>
        )}
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('chatSettings.hint')}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { alignItems: 'center', justifyContent: 'center' },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 16, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center' },
  well: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: { flex: 1, gap: 2 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  tile: { width: '31%', borderRadius: 14, overflow: 'hidden' },
  tileImage: { width: '100%', aspectRatio: 9 / 13 },
  tileLabel: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  preview: {
    height: 220,
    borderRadius: 18,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
    justifyContent: 'space-between',
  },
  previewBody: { padding: 14, gap: 8 },
  bubble: { maxWidth: '75%', borderRadius: 16, paddingHorizontal: 12, paddingVertical: 8 },
  mine: { alignSelf: 'flex-end' },
  theirs: { alignSelf: 'flex-start' },
  previewComposer: { alignItems: 'center', gap: 8, padding: 10 },
  previewField: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  previewSend: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
