import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { accountKeys, answerFollowRequest, listFollowRequests } from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

/** Follow requests to my private account (POST-006, PROF-004): approve to let someone see my stories, or
 * decline. Without this, a private account could never gain followers. */
export default function FollowRequestsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const requests = useQuery({
    queryKey: accountKeys.followRequests,
    queryFn: () => listFollowRequests(getApiClient()),
  });
  const answer = useMutation({
    mutationFn: ({ userId, approve }: { userId: string; approve: boolean }) =>
      answerFollowRequest(getApiClient(), userId, approve),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: accountKeys.followRequests }),
  });
  const people = requests.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('followRequests.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {requests.isPending ? <ActivityIndicator /> : null}
        {requests.isError ? (
          <Notice tone="error" testID="follow-requests-error">
            {t('followRequests.error')}
          </Notice>
        ) : null}
        {answer.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        {requests.isSuccess && people.length === 0 ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="follow-requests-empty"
          >
            {t('followRequests.empty')}
          </Text>
        ) : null}
        {people.map((person) => (
          <View key={person.id} style={styles.row} testID={`follow-request-${person.id}`}>
            <Pressable
              onPress={() => router.push({ pathname: '/user/[id]', params: { id: person.id } })}
              accessibilityRole="link"
              style={[styles.row, styles.fill]}
            >
              <Avatar user={person} size={40} />
              <View style={styles.fill}>
                <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                  {person.display_name}
                </Text>
                <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                  @{person.handle}
                </Text>
              </View>
            </Pressable>
            <Button
              label={t('followRequests.approve')}
              onPress={() => answer.mutate({ userId: person.id, approve: true })}
              testID={`follow-approve-${person.id}`}
            />
            <Button
              label={t('followRequests.decline')}
              variant="secondary"
              onPress={() => answer.mutate({ userId: person.id, approve: false })}
              testID={`follow-decline-${person.id}`}
            />
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});
