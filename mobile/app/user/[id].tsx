import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice } from '@/components/Form';
import {
  accountKeys,
  block,
  fetchProfile,
  fetchUserPosts,
  sendConnectionRequest,
  setFollowing,
} from '@/features/account/api';
import { feedKeys } from '@/features/feed/api';
import { Avatar, PostCard } from '@/features/feed/PostCard';
import type { Post } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-102 Another traveller's profile: follow, block, report and their stories. */
export default function UserProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const myId = useSessionStore((state) => state.me?.account.id);
  const profile = useQuery({
    queryKey: accountKeys.profile(id),
    queryFn: () => fetchProfile(getApiClient(), id),
  });
  const restricted = profile.data?.is_restricted ?? true;
  const posts = useQuery({
    queryKey: accountKeys.posts(id),
    queryFn: () => fetchUserPosts(getApiClient(), id),
    enabled: profile.isSuccess && !restricted,
  });
  const follow = useMutation({
    mutationFn: (next: boolean) => setFollowing(getApiClient(), id, next),
    onSuccess: (status) => {
      queryClient.setQueryData(accountKeys.profile(id), (old: typeof profile.data) =>
        old ? { ...old, follow_status: status } : old,
      );
      void queryClient.invalidateQueries({ queryKey: accountKeys.profile(id) });
    },
  });
  const connectKey = useRef(getApiClient().newIdempotencyKey());
  const connect = useMutation({
    mutationFn: () => sendConnectionRequest(getApiClient(), id, connectKey.current),
    onSuccess: () => {
      queryClient.setQueryData(accountKeys.profile(id), (old: typeof profile.data) =>
        old ? { ...old, relationship: 'request_pending', can_request_connection: false } : old,
      );
      void queryClient.invalidateQueries({ queryKey: accountKeys.requests('outgoing') });
    },
  });
  const blockUser = useMutation({
    mutationFn: () => block(getApiClient(), id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: feedKeys.all });
      void queryClient.invalidateQueries({ queryKey: accountKeys.blocks });
      router.back();
    },
  });

  const data = profile.data;
  const isMe = myId === id;
  const header = profile.isPending ? (
    <ActivityIndicator color={theme.colors.primary} />
  ) : !data ? (
    <Notice tone="error" testID="user-not-found">
      {t('user.notFound')}
    </Notice>
  ) : (
    <View style={{ gap: theme.spacing[3], paddingBottom: theme.spacing[3] }}>
      <View style={styles.header}>
        <Avatar user={data} size={64} />
        <View style={styles.fill}>
          <Text
            accessibilityRole="header"
            style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
          >
            {data.display_name}
          </Text>
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            @{data.handle}
          </Text>
        </View>
      </View>
      {data.bio ? (
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>{data.bio}</Text>
      ) : null}
      {data.counts ? (
        <Text
          style={[theme.typography.label, { color: theme.colors.textSecondary }]}
          testID="user-counts"
        >
          {t('user.counts', data.counts)}
        </Text>
      ) : null}
      {restricted ? <Notice tone="info">{t('user.private')}</Notice> : null}
      {!isMe ? (
        <View style={{ gap: theme.spacing[2] }}>
          <Button
            label={
              data.follow_status === 'following'
                ? t('user.unfollow')
                : data.follow_status === 'requested'
                  ? t('user.requested')
                  : t('user.follow')
            }
            variant={data.follow_status === 'none' ? 'primary' : 'secondary'}
            onPress={() => follow.mutate(data.follow_status === 'none')}
            busy={follow.isPending}
            testID="user-follow"
          />
          {data.relationship === 'connected' ? (
            <Notice tone="success" testID="user-connected">
              {t('user.connected')}
            </Notice>
          ) : data.relationship === 'request_received' ? (
            <Button
              label={t('user.respondToRequest')}
              variant="secondary"
              onPress={() => router.push('/companions')}
              testID="user-respond"
            />
          ) : data.relationship === 'request_pending' ? (
            <Text
              style={[theme.typography.label, { color: theme.colors.textSecondary }]}
              testID="user-request-sent"
            >
              {t('user.requestSent')}
            </Text>
          ) : data.can_request_connection ? (
            <Button
              label={t('user.connect')}
              variant="secondary"
              onPress={() => connect.mutate()}
              busy={connect.isPending}
              testID="user-connect"
            />
          ) : null}
          {connect.isError ? (
            <Notice tone="error">
              {connect.error instanceof ApiProblem &&
              connect.error.code === 'connection_request_not_allowed'
                ? t('user.connectNotAllowed')
                : t('user.actionFailed')}
            </Notice>
          ) : null}
          <View style={styles.actions}>
            <View style={styles.fill}>
              <Button
                label={t('user.report')}
                variant="secondary"
                onPress={() =>
                  router.push({
                    pathname: '/report',
                    params: { type: 'user', target: id, name: data.display_name },
                  })
                }
                testID="user-report"
              />
            </View>
            <View style={styles.fill}>
              <Button
                label={t('user.block')}
                variant="secondary"
                onPress={() => blockUser.mutate()}
                busy={blockUser.isPending}
                testID="user-block"
              />
            </View>
          </View>
          {follow.isError || blockUser.isError ? (
            <Notice tone="error">{t('user.actionFailed')}</Notice>
          ) : null}
        </View>
      ) : null}
    </View>
  );

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: data ? `@${data.handle}` : '' }} />
      <FlatList<Post>
        data={posts.data?.data ?? []}
        keyExtractor={(post) => post.id}
        ListHeaderComponent={header}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        renderItem={({ item }) => (
          <PostCard
            post={item}
            onOpen={(post) => router.push({ pathname: '/post/[id]', params: { id: post.id } })}
          />
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  actions: { flexDirection: 'row', gap: 8 },
});
