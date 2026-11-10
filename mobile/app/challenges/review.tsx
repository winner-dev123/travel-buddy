import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import {
  challengeKeys,
  getResults,
  judgeSubmission,
  type Judgement,
  listReviewQueue,
  updateWinner,
} from '@/features/challenges/api';
import { useAppTheme } from '@/theme/useAppTheme';

const VERDICTS: readonly Judgement[] = ['correct', 'incorrect', 'void'];

/** SCR-090 Judge review queue (CHAL-006, CHAL-007, CHAL-010): answers waiting for a decision,
 * with the AI judge's advice, and the winners to confirm or revoke before results go out.
 * Judges never decide their own answers; the server refuses it. */
export default function ReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const queue = useQuery({
    queryKey: challengeKeys.review(id),
    queryFn: () => listReviewQueue(getApiClient(), id),
  });
  const results = useQuery({
    queryKey: challengeKeys.results(id),
    queryFn: () => getResults(getApiClient(), id),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: challengeKeys.review(id) });
    void queryClient.invalidateQueries({ queryKey: challengeKeys.results(id) });
    void queryClient.invalidateQueries({ queryKey: challengeKeys.detail(id) });
  };
  const judge = useMutation({
    mutationFn: ({ submission, verdict }: { submission: string; verdict: Judgement }) =>
      judgeSubmission(getApiClient(), id, submission, verdict),
    onSuccess: refresh,
  });
  const winner = useMutation({
    mutationFn: ({ winnerId, action }: { winnerId: string; action: 'confirm' | 'revoke' }) =>
      updateWinner(getApiClient(), id, winnerId, action),
    onSuccess: refresh,
  });
  const failed = judge.error ?? winner.error;
  const error =
    failed instanceof ApiProblem && failed.code === 'forbidden'
      ? t('challenges.review.ownAnswer')
      : failed instanceof ApiProblem && failed.code === 'conflict'
        ? t('challenges.review.final')
        : failed
          ? t('user.actionFailed')
          : null;
  const items = queue.data ?? [];
  const winners = (results.data?.winners ?? []).filter((w) => w.status !== 'revoked');

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('challenges.review.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {queue.isPending ? <ActivityIndicator color={theme.colors.primary} /> : null}
        {error ? <Notice tone="error">{error}</Notice> : null}
        {queue.isSuccess && items.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('challenges.review.empty')}
          </Text>
        ) : null}
        {items.map((submission) => (
          <View
            key={submission.id}
            style={[styles.card, { borderColor: theme.colors.divider, gap: theme.spacing[1] }]}
            testID={`review-${submission.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {submission.answer_text}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {submission.submitted_by?.display_name ?? '—'} ·{' '}
              {t(`challenges.review.status.${submission.evaluation_status}`)}
            </Text>
            {submission.ai_rationale ? (
              <Text
                style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                testID={`review-ai-${submission.id}`}
              >
                {t('challenges.review.ai', {
                  confidence: Math.round((submission.ai_confidence ?? 0) * 100),
                  rationale: submission.ai_rationale,
                })}
              </Text>
            ) : null}
            <View style={styles.row}>
              {VERDICTS.map((verdict) => (
                <Pressable
                  key={verdict}
                  accessibilityRole="button"
                  onPress={() => judge.mutate({ submission: submission.id, verdict })}
                  style={[styles.chip, { borderColor: theme.colors.primary }]}
                  testID={`review-${verdict}-${submission.id}`}
                >
                  <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                    {t(`challenges.review.verdicts.${verdict}`)}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        ))}

        {winners.length > 0 ? (
          <Text
            accessibilityRole="header"
            style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
          >
            {t('challenges.review.winners')}
          </Text>
        ) : null}
        {winners.map((w) => (
          <View key={w.id} style={styles.row} testID={`review-winner-${w.id}`}>
            <Text style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}>
              {t('challenges.winnerLine', {
                rank: w.rank,
                name: w.team?.name ?? w.user?.display_name ?? '—',
              })}
              {w.status === 'provisional' ? ` (${t('challenges.provisional')})` : ''}
            </Text>
            {w.status === 'provisional' ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => winner.mutate({ winnerId: w.id, action: 'confirm' })}
                style={[styles.chip, { borderColor: theme.colors.primary }]}
                testID={`review-confirm-${w.id}`}
              >
                <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                  {t('challenges.review.confirm')}
                </Text>
              </Pressable>
            ) : null}
            <Pressable
              accessibilityRole="button"
              onPress={() => winner.mutate({ winnerId: w.id, action: 'revoke' })}
              testID={`review-revoke-${w.id}`}
            >
              <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
                {t('challenges.review.revoke')}
              </Text>
            </Pressable>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12 },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
