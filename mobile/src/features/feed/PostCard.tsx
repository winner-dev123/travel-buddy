import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { getApiClient } from '@/api';
import { useAppTheme } from '@/theme/useAppTheme';

import { setReaction } from './api';
import { TranslatableBody } from './TranslatableBody';
import type { MediaRef, Post, UserSummary } from './types';

export function Avatar({ user, size = 40 }: { user: UserSummary | null; size?: number }) {
  const theme = useAppTheme();
  const url = user?.avatar?.status === 'ready' ? user.avatar.url : null;
  const initial = (user?.display_name ?? '?').trim().charAt(0).toUpperCase() || '?';
  const shape = { width: size, height: size, borderRadius: size / 2 };
  return url ? (
    <Image source={{ uri: url }} style={shape} accessibilityIgnoresInvertColors />
  ) : (
    <View
      style={[shape, styles.center, { backgroundColor: theme.colors.primary }]}
      accessibilityElementsHidden
      importantForAccessibility="no"
    >
      <Text style={[theme.typography.label, { color: theme.colors.onPrimary }]}>{initial}</Text>
    </View>
  );
}

function MediaPreview({ media }: { media: MediaRef }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const ratio = media.width && media.height ? media.width / media.height : 4 / 3;
  if (media.status === 'ready' && media.url) {
    return (
      <Image
        source={{ uri: media.url }}
        style={[styles.media, { aspectRatio: Math.max(0.6, Math.min(ratio, 2)) }]}
        accessibilityLabel={media.alt_text ?? t('post.photo')}
      />
    );
  }
  return (
    <View
      style={[
        styles.media,
        styles.center,
        { aspectRatio: 4 / 3, backgroundColor: theme.colors.surface },
      ]}
    >
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {media.status === 'processing' ? t('post.photoProcessing') : t('post.photoUnavailable')}
      </Text>
    </View>
  );
}

export interface PostCardProps {
  post: Post;
  onOpen?: (post: Post) => void;
  /** Tapping the author opens their profile (signed in only). */
  onOpenAuthor?: (userId: string) => void;
  /** Guests can read but not react. */
  interactive?: boolean;
}

/** One story in a feed (SCR-021 card). */
export function PostCard({ post, onOpen, onOpenAuthor, interactive = true }: PostCardProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const [liked, setLiked] = useState(Boolean(post.viewer?.reaction));
  const [count, setCount] = useState(post.counts.reactions);
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    if (busy) return;
    const next = !liked;
    setBusy(true);
    setLiked(next);
    setCount((c) => c + (next ? 1 : -1));
    try {
      await setReaction(getApiClient(), post.id, next ? 'like' : null);
    } catch {
      setLiked(!next); // revert: the server state did not change
      setCount((c) => c + (next ? -1 : 1));
    } finally {
      setBusy(false);
    }
  };

  const place = post.primary_destination?.name;
  return (
    <Pressable
      onPress={() => onOpen?.(post)}
      accessibilityRole="button"
      accessibilityLabel={t('post.openA11y', { name: post.author.display_name })}
      style={[
        styles.card,
        { backgroundColor: theme.colors.surfaceRaised, borderColor: theme.colors.divider },
      ]}
      testID={`post-card-${post.id}`}
    >
      <Pressable
        style={styles.header}
        onPress={onOpenAuthor ? () => onOpenAuthor(post.author.id) : undefined}
        disabled={!onOpenAuthor}
        accessibilityRole={onOpenAuthor ? 'link' : undefined}
        accessibilityLabel={
          onOpenAuthor ? t('post.authorA11y', { name: post.author.display_name }) : undefined
        }
        testID={`post-author-${post.id}`}
      >
        <Avatar user={post.author} />
        <View style={styles.headerText}>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {post.author.display_name}
          </Text>
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {[`@${post.author.handle}`, place, t(`post.kinds.${post.kind}`)]
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </View>
      </Pressable>
      {post.body ? <TranslatableBody post={post} enabled={interactive} /> : null}
      {post.media[0] ? <MediaPreview media={post.media[0]} /> : null}
      {post.tags.length > 0 ? (
        <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>
          {post.tags.map((tag) => `#${tag}`).join('  ')}
        </Text>
      ) : null}
      <View style={styles.footer}>
        <Pressable
          onPress={interactive ? toggle : undefined}
          disabled={!interactive}
          accessibilityRole="button"
          accessibilityState={{ selected: liked, disabled: !interactive }}
          accessibilityLabel={liked ? t('post.unlike') : t('post.like')}
          hitSlop={8}
          style={styles.action}
          testID={`post-like-${post.id}`}
        >
          <Ionicons
            name={liked ? 'heart' : 'heart-outline'}
            size={20}
            color={liked ? theme.colors.danger : theme.colors.textSecondary}
          />
          <Text
            style={[theme.typography.label, { color: theme.colors.textSecondary }]}
            testID={`post-likes-${post.id}`}
          >
            {count}
          </Text>
        </Pressable>
        <View
          style={styles.action}
          accessibilityLabel={t('post.commentsCount', { count: post.counts.comments })}
        >
          <Ionicons name="chatbubble-outline" size={18} color={theme.colors.textSecondary} />
          <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
            {post.counts.comments}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 16, gap: 12 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  headerText: { flex: 1 },
  center: { alignItems: 'center', justifyContent: 'center' },
  media: { width: '100%', borderRadius: 8 },
  footer: { flexDirection: 'row', gap: 24 },
  action: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 32 },
});
