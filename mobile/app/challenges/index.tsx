import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { challengeKeys, listGroupChallenges } from '@/features/challenges/api';
import { getGroup, groupKeys } from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-085 Group challenges (BL-5.08): published riddles for members; drafts and "New challenge"
 * for organizers (`challenges.manage`, premium-gated on the server). */
export default function ChallengesScreen() {
  const { groupId } = useLocalSearchParams<{ groupId: string }>();
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const group = useQuery({
    queryKey: groupKeys.detail(groupId),
    queryFn: () => getGroup(getApiClient(), groupId),
  });
  const list = useQuery({
    queryKey: challengeKeys.group(groupId),
    queryFn: () => listGroupChallenges(getApiClient(), groupId),
  });
  const canManage = (group.data?.my_membership?.permissions ?? []).includes('challenges.manage');
  const challenges = list.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('challenges.listTitle') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {canManage ? (
          <Button
            label={t('challenges.new')}
            onPress={() => router.push({ pathname: '/challenges/new', params: { groupId } })}
            testID="challenges-new"
          />
        ) : null}
        <Button
          label={t('challenges.myRewards')}
          variant="secondary"
          onPress={() => router.push('/rewards')}
          testID="challenges-rewards"
        />
        {list.isPending ? <ActivityIndicator color={theme.colors.primary} /> : null}
        {list.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        {list.isSuccess && challenges.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('challenges.empty')}
          </Text>
        ) : null}
        {challenges.map((challenge) => (
          <Pressable
            key={challenge.id}
            accessibilityRole="button"
            onPress={() =>
              router.push({ pathname: '/challenges/[id]', params: { id: challenge.id } })
            }
            style={[styles.card, { borderColor: theme.colors.divider, gap: theme.spacing[1] }]}
            testID={`challenge-${challenge.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {challenge.title}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t(`challenges.status.${challenge.status}`)} ·{' '}
              {new Date(challenge.ends_at).toLocaleDateString(i18n.language)}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12 },
});
