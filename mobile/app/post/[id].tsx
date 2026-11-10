import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
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
  createComment,
  deleteComment,
  feedKeys,
  fetchComments,
  fetchPost,
  fetchReplies,
} from '@/features/feed/api';
import { AuthorTools } from '@/features/feed/AuthorTools';
import { Avatar, PostCard } from '@/features/feed/PostCard';
import type { Comment } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-022 Post detail: the story with its comments (signed in) and a reply box. */
export default function PostDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const queryClient = useQueryClient();
  const router = useRouter();
  const [draft, setDraft] = useState('');
  const [replyTo, setReplyTo] = useState<Comment | null>(null);
  const [openReplies, setOpenReplies] = useState<Set<string>>(new Set());
  // One idempotency key per comment the user writes; retries of the same comment reuse it.
  const commentKey = useRef<string>(getApiClient().newIdempotencyKey());

  const post = useQuery({
    queryKey: feedKeys.post(id),
    queryFn: () => fetchPost(getApiClient(), id, signedIn),
  });
  const comments = useQuery({
    queryKey: feedKeys.comments(id),
    queryFn: () => fetchComments(getApiClient(), id),
    enabled: signedIn,
  });
  const send = useMutation({
    mutationFn: (body: string) =>
      createComment(getApiClient(), id, body, commentKey.current, replyTo?.id),
    onSuccess: () => {
      setDraft('');
      commentKey.current = getApiClient().newIdempotencyKey();
      if (replyTo) {
        setOpenReplies((open) => new Set(open).add(replyTo.id)); // show the new reply
        void queryClient.invalidateQueries({ queryKey: feedKeys.replies(replyTo.id) });
      }
      setReplyTo(null);
      void queryClient.invalidateQueries({ queryKey: feedKeys.comments(id) });
    },
  });
  const toggleReplies = (commentId: string) =>
    setOpenReplies((open) => {
      const next = new Set(open);
      if (next.has(commentId)) next.delete(commentId);
      else next.add(commentId);
      return next;
    });

  const canComment = signedIn && (post.data?.viewer?.can_comment ?? false);
  const meId = useSessionStore((state) => state.me?.account.id);
  const removeComment = useMutation({
    mutationFn: (commentId: string) => deleteComment(getApiClient(), commentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: feedKeys.comments(id) }),
  });
  const commentActions = (comment: Comment) => {
    if (!signedIn || comment.deleted) return;
    const mine = comment.author?.id === meId;
    const options = [
      ...(comment.viewer?.can_delete
        ? [
            {
              text: t('post.deleteComment'),
              style: 'destructive' as const,
              onPress: () => removeComment.mutate(comment.id),
            },
          ]
        : []),
      ...(!mine
        ? [
            {
              text: t('post.reportComment'),
              onPress: () =>
                router.push({
                  pathname: '/report',
                  params: {
                    type: 'comment',
                    target: comment.id,
                    name: comment.author?.display_name ?? '',
                  },
                }),
            },
          ]
        : []),
    ];
    if (options.length === 0) return;
    Alert.alert(t('post.commentActions'), undefined, [
      ...options,
      { text: t('common.cancel'), style: 'cancel' },
    ]);
  };
  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('post.title') }} />
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <FlatList<Comment>
          data={comments.data?.data ?? []}
          keyExtractor={(comment) => comment.id}
          contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
          ListHeaderComponent={
            post.isPending ? (
              <ActivityIndicator color={theme.colors.primary} />
            ) : post.isError || !post.data ? (
              <Notice tone="error" testID="post-error">
                {t('post.notFound')}
              </Notice>
            ) : (
              <View style={{ gap: theme.spacing[4] }}>
                <PostCard
                  post={post.data}
                  interactive={signedIn}
                  onOpenAuthor={
                    signedIn
                      ? (userId) => router.push({ pathname: '/user/[id]', params: { id: userId } })
                      : undefined
                  }
                />
                {post.data.place ? (
                  <Button
                    label={t('post.viewPlace', { name: post.data.place.name })}
                    variant="secondary"
                    onPress={() =>
                      router.push({
                        pathname: '/places/[id]',
                        params: { id: post.data.place?.id ?? '' },
                      })
                    }
                    testID="post-place"
                  />
                ) : null}
                {signedIn && post.data.viewer?.is_author ? <AuthorTools post={post.data} /> : null}
                {signedIn && !post.data.viewer?.is_author ? (
                  <Button
                    label={t('post.report')}
                    variant="secondary"
                    onPress={() =>
                      router.push({
                        pathname: '/report',
                        params: {
                          type: 'post',
                          target: post.data.id,
                          name: post.data.author.display_name,
                        },
                      })
                    }
                    testID="post-report"
                  />
                ) : null}
                <Text
                  accessibilityRole="header"
                  style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                >
                  {t('post.comments')}
                </Text>
                {!signedIn ? (
                  <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                    {t('post.signInToComment')}
                  </Text>
                ) : null}
              </View>
            )
          }
          renderItem={({ item }) => (
            <Pressable
              onLongPress={() => commentActions(item)}
              accessibilityHint={signedIn ? t('post.commentActionsHint') : undefined}
              style={styles.comment}
              testID={`comment-${item.id}`}
            >
              <Avatar user={item.author} size={32} />
              <View style={styles.fill}>
                <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                  {item.author?.display_name ?? t('post.deletedUser')}
                </Text>
                <Text
                  style={[
                    theme.typography.body,
                    { color: item.deleted ? theme.colors.textSecondary : theme.colors.textPrimary },
                  ]}
                >
                  {item.deleted ? t('post.commentDeleted') : item.body}
                </Text>
                <View style={styles.commentLinks}>
                  {canComment && !item.deleted ? (
                    <Pressable
                      onPress={() => setReplyTo(item)}
                      accessibilityRole="button"
                      hitSlop={6}
                      testID={`comment-reply-${item.id}`}
                    >
                      <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>
                        {t('post.reply')}
                      </Text>
                    </Pressable>
                  ) : null}
                  {(item.reply_count ?? 0) > 0 ? (
                    <Pressable
                      onPress={() => toggleReplies(item.id)}
                      accessibilityRole="button"
                      accessibilityState={{ expanded: openReplies.has(item.id) }}
                      hitSlop={6}
                      testID={`comment-replies-${item.id}`}
                    >
                      <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>
                        {openReplies.has(item.id)
                          ? t('post.hideReplies')
                          : t('post.viewReplies', { count: item.reply_count ?? 0 })}
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
                {openReplies.has(item.id) ? (
                  <Replies commentId={item.id} onActions={commentActions} />
                ) : null}
              </View>
            </Pressable>
          )}
          ListEmptyComponent={
            signedIn && comments.isSuccess ? (
              <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                {t('post.noComments')}
              </Text>
            ) : undefined
          }
        />
        {canComment ? (
          <View
            style={[
              styles.composer,
              { borderTopColor: theme.colors.divider, padding: theme.spacing[3] },
            ]}
          >
            {send.isError ? <Notice tone="error">{t('post.commentFailed')}</Notice> : null}
            {replyTo ? (
              <View style={styles.commentLinks} testID="comment-replying">
                <Text
                  numberOfLines={1}
                  style={[
                    styles.fill,
                    theme.typography.caption,
                    { color: theme.colors.textSecondary },
                  ]}
                >
                  {t('post.replyingTo', {
                    name: replyTo.author?.display_name ?? t('post.deletedUser'),
                  })}
                </Text>
                <Pressable
                  onPress={() => setReplyTo(null)}
                  accessibilityRole="button"
                  accessibilityLabel={t('post.cancelReply')}
                  testID="comment-cancel-reply"
                >
                  <Text style={[theme.typography.label, { color: theme.colors.primary }]}>✕</Text>
                </Pressable>
              </View>
            ) : null}
            <TextField
              label={t('post.addComment')}
              value={draft}
              onChangeText={setDraft}
              maxLength={2000}
              multiline
              testID="comment-input"
            />
            <Button
              label={t('post.send')}
              onPress={() => send.mutate(draft.trim())}
              disabled={draft.trim().length === 0}
              busy={send.isPending}
              testID="comment-send"
            />
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/** One comment's replies, loaded when opened. */
function Replies({
  commentId,
  onActions,
}: {
  commentId: string;
  onActions: (comment: Comment) => void;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const replies = useQuery({
    queryKey: feedKeys.replies(commentId),
    queryFn: () => fetchReplies(getApiClient(), commentId),
  });
  if (replies.isPending) return <ActivityIndicator />;
  return (
    <View style={styles.replies} testID={`replies-${commentId}`}>
      {(replies.data?.data ?? []).map((reply) => (
        <Pressable
          key={reply.id}
          onLongPress={() => onActions(reply)}
          style={styles.comment}
          testID={`comment-${reply.id}`}
        >
          <Avatar user={reply.author} size={24} />
          <View style={styles.fill}>
            <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
              {reply.author?.display_name ?? t('post.deletedUser')}
            </Text>
            <Text
              style={[
                theme.typography.body,
                { color: reply.deleted ? theme.colors.textSecondary : theme.colors.textPrimary },
              ]}
            >
              {reply.deleted ? t('post.commentDeleted') : reply.body}
            </Text>
          </View>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  commentLinks: { flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 4 },
  replies: { gap: 8, marginTop: 8 },
  comment: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  composer: { borderTopWidth: 1, gap: 8 },
});
