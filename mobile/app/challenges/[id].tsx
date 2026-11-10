import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import {
  type Challenge,
  type ChallengeTeam,
  challengeKeys,
  createTeam,
  getChallenge,
  getManagerView,
  getResults,
  joinTeam,
  listTeams,
  publishChallenge,
  publishResults,
  submitAnswer,
  type SubmissionResult,
} from '@/features/challenges/api';
import { getGroup, groupKeys } from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

function when(iso: string, locale: string): string {
  return new Date(iso).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Submission problems people can act on (CHAL-004, CHAL-005); the rest is a generic failure. */
const SUBMIT_ERRORS = {
  attempts_exhausted: 'challenges.errors.exhausted',
  attempt_cooldown: 'challenges.errors.cooldown',
  challenge_not_active: 'challenges.errors.notActive',
  not_team_captain: 'challenges.errors.notCaptain',
  rate_limited: 'challenges.errors.tooFast',
  forbidden: 'challenges.errors.organizer',
  conflict: 'challenges.errors.solved',
} as const;

function submitErrorKey(error: unknown) {
  if (error instanceof ApiProblem && error.code in SUBMIT_ERRORS) {
    return SUBMIT_ERRORS[error.code as keyof typeof SUBMIT_ERRORS];
  }
  return 'user.actionFailed' as const;
}

/** SCR-086 Challenge detail and submit, with SCR-088 results inline (BL-5.08): the riddle, released hints, answering (captains in team mode),
 * teams and their thread, and results once published. Answers are never shown (CHAL-008). */
export default function ChallengeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = useRef(getApiClient().newIdempotencyKey());
  const [answer, setAnswer] = useState('');
  const [teamName, setTeamName] = useState('');
  const [outcome, setOutcome] = useState<SubmissionResult | null>(null);

  const challenge = useQuery({
    queryKey: challengeKeys.detail(id),
    queryFn: () => getChallenge(getApiClient(), id),
  });
  const groupId = challenge.data?.group_id ?? '';
  const group = useQuery({
    queryKey: groupKeys.detail(groupId),
    queryFn: () => getGroup(getApiClient(), groupId),
    enabled: groupId !== '',
  });
  const permissions = group.data?.my_membership?.permissions ?? [];
  const canManage = permissions.includes('challenges.manage');
  const canJudge = permissions.includes('challenges.judge');
  const published = Boolean(challenge.data?.results_published_at);
  const results = useQuery({
    queryKey: challengeKeys.results(id),
    queryFn: () => getResults(getApiClient(), id),
    enabled: challenge.data !== undefined && (published || canJudge),
  });
  const teamMode = challenge.data?.solving_mode === 'team';
  const teams = useQuery({
    queryKey: challengeKeys.teams(id),
    queryFn: () => listTeams(getApiClient(), id),
    enabled: teamMode,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: challengeKeys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: challengeKeys.teams(id) });
    void queryClient.invalidateQueries({ queryKey: challengeKeys.results(id) });
  };
  const submit = useMutation({
    mutationFn: () => submitAnswer(getApiClient(), id, key.current, answer.trim()),
    onSuccess: (result) => {
      setOutcome(result);
      setAnswer('');
      key.current = getApiClient().newIdempotencyKey();
      refresh();
    },
  });
  const create = useMutation({
    mutationFn: () => createTeam(getApiClient(), id, teamName.trim()),
    onSuccess: () => {
      setTeamName('');
      refresh();
    },
  });
  const join = useMutation({
    mutationFn: (teamId: string) => joinTeam(getApiClient(), id, teamId),
    onSuccess: refresh,
  });
  const publish = useMutation({
    mutationFn: async () => {
      const view = await getManagerView(getApiClient(), id);
      return publishChallenge(getApiClient(), id, view.version);
    },
    onSuccess: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: challengeKeys.group(groupId) });
    },
  });
  const finish = useMutation({
    mutationFn: () => publishResults(getApiClient(), id),
    onSuccess: refresh,
  });

  if (challenge.isPending) {
    return <ActivityIndicator color={theme.colors.primary} style={styles.loading} />;
  }
  if (challenge.isError || !challenge.data) {
    return <Notice tone="error">{t('challenges.notFound')}</Notice>;
  }
  const data: Challenge = challenge.data;
  const mine = data.my_participation;
  const myTeam: ChallengeTeam | undefined = (teams.data?.data ?? []).find(
    (team) => team.id === mine?.team_id,
  );
  const solved = outcome?.evaluation_status === 'correct';
  const canAnswer =
    data.status === 'active' &&
    !solved &&
    !canJudge &&
    (!teamMode || (Boolean(mine?.team_id) && mine?.is_captain === true));
  const submitError = submit.isError ? t(submitErrorKey(submit.error)) : null;
  const teamProblem = create.error ?? join.error;
  const teamError = teamProblem
    ? t(
        teamProblem instanceof ApiProblem && teamProblem.code === 'conflict'
          ? 'challenges.errors.team'
          : 'user.actionFailed',
      )
    : null;
  const textStyle = [theme.typography.body, { color: theme.colors.textPrimary }];
  const mutedStyle = [theme.typography.caption, { color: theme.colors.textSecondary }];
  const headerStyle = [theme.typography.title3, { color: theme.colors.textPrimary }];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('challenges.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.title2, { color: theme.colors.textPrimary }]}>
          {data.title}
        </Text>
        <Text style={mutedStyle} testID="challenge-status">
          {t(`challenges.status.${data.status}`)} ·{' '}
          {t('challenges.window', {
            start: when(data.starts_at, i18n.language),
            end: when(data.ends_at, i18n.language),
          })}
        </Text>
        <Text style={textStyle}>{data.description}</Text>
        {data.prize_description ? (
          <Text style={textStyle}>{t('challenges.prize', { prize: data.prize_description })}</Text>
        ) : null}
        {data.rewards.map((reward) => (
          <Text key={reward.id} style={mutedStyle} testID={`challenge-reward-${reward.id}`}>
            {t(`challenges.rewardTypes.${reward.reward_type}`)}: {reward.title}
            {reward.sponsor_name ? ` (${reward.sponsor_name})` : ''}
          </Text>
        ))}
        {data.participation_rules ? (
          <Text style={mutedStyle}>{data.participation_rules}</Text>
        ) : null}

        {data.hints.length > 0 ? (
          <>
            <Text accessibilityRole="header" style={headerStyle}>
              {t('challenges.hints')}
            </Text>
            {data.hints.map((hint) => (
              <Text key={hint.id} style={textStyle} testID={`challenge-hint-${hint.id}`}>
                • {hint.body}
              </Text>
            ))}
          </>
        ) : null}

        {data.status === 'draft' && canManage ? (
          <>
            <Notice tone="info">{t('challenges.draftNote')}</Notice>
            <Button
              label={t('challenges.publish')}
              onPress={() => publish.mutate()}
              busy={publish.isPending}
              testID="challenge-publish"
            />
            {publish.isError ? (
              <Notice tone="error">
                {publish.error instanceof ApiProblem && publish.error.code === 'conflict'
                  ? t('challenges.reviewPending')
                  : t('user.actionFailed')}
              </Notice>
            ) : null}
          </>
        ) : null}
        {data.status === 'scheduled' ? (
          <Notice tone="info">
            {t('challenges.startsAt', { time: when(data.starts_at, i18n.language) })}
          </Notice>
        ) : null}

        {mine ? (
          <Text style={mutedStyle} testID="challenge-attempts">
            {t('challenges.attempts', { count: mine.attempts_remaining })}
            {mine.next_attempt_at
              ? ` · ${t('challenges.nextAttempt', { time: when(mine.next_attempt_at, i18n.language) })}`
              : ''}
          </Text>
        ) : null}

        {teamMode && (data.status === 'active' || data.status === 'scheduled') && !canJudge ? (
          <>
            <Text accessibilityRole="header" style={headerStyle}>
              {t('challenges.teams')}
            </Text>
            {myTeam ? (
              <>
                <Text style={textStyle} testID="challenge-my-team">
                  {t('challenges.myTeam', {
                    name: myTeam.name,
                    captain: myTeam.captain?.display_name ?? '—',
                  })}
                </Text>
                {!mine?.is_captain ? (
                  <Notice tone="info" testID="challenge-captain-only">
                    {t('challenges.captainOnly')}
                  </Notice>
                ) : null}
                {myTeam.conversation_id ? (
                  <Button
                    label={t('challenges.teamChat')}
                    variant="secondary"
                    onPress={() =>
                      router.push({
                        pathname: '/chat/[id]',
                        params: { id: myTeam.conversation_id! },
                      })
                    }
                    testID="challenge-team-chat"
                  />
                ) : null}
              </>
            ) : (
              <>
                {(teams.data?.data ?? []).map((team) => (
                  <View key={team.id} style={styles.row}>
                    <Text style={[styles.fill, ...textStyle]}>
                      {t('challenges.teamLine', { name: team.name, count: team.members.length })}
                    </Text>
                    <Pressable
                      accessibilityRole="button"
                      onPress={() => join.mutate(team.id)}
                      style={[styles.chip, { borderColor: theme.colors.primary }]}
                      testID={`challenge-join-${team.id}`}
                    >
                      <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                        {t('challenges.join')}
                      </Text>
                    </Pressable>
                  </View>
                ))}
                <TextField
                  label={t('challenges.teamName')}
                  value={teamName}
                  onChangeText={setTeamName}
                  maxLength={40}
                  testID="challenge-team-name"
                />
                <Button
                  label={t('challenges.createTeam')}
                  variant="secondary"
                  onPress={() => create.mutate()}
                  disabled={teamName.trim().length < 2}
                  busy={create.isPending}
                  testID="challenge-create-team"
                />
                {teamError ? <Notice tone="error">{teamError}</Notice> : null}
              </>
            )}
          </>
        ) : null}

        {canAnswer ? (
          <>
            <TextField
              label={t('challenges.answer')}
              value={answer}
              onChangeText={setAnswer}
              maxLength={500}
              autoCorrect={false}
              testID="challenge-answer"
            />
            <Button
              label={t('challenges.submit')}
              onPress={() => submit.mutate()}
              disabled={answer.trim().length === 0}
              busy={submit.isPending}
              testID="challenge-submit"
            />
          </>
        ) : null}
        {outcome ? (
          <Notice
            tone={outcome.evaluation_status === 'correct' ? 'success' : 'info'}
            testID="challenge-outcome"
          >
            {outcome.evaluation_status === 'correct'
              ? outcome.is_provisional_winner
                ? t('challenges.correctWinner')
                : t('challenges.correct')
              : outcome.evaluation_status === 'incorrect'
                ? t('challenges.incorrect', { count: outcome.attempts_remaining })
                : t('challenges.pending')}
          </Notice>
        ) : null}
        {submitError ? (
          <Notice tone="error" testID="challenge-error">
            {submitError}
          </Notice>
        ) : null}

        {published || data.status === 'judging' || data.status === 'completed' ? (
          <>
            <Text accessibilityRole="header" style={headerStyle}>
              {t('challenges.results')}
            </Text>
            {published ? null : <Text style={mutedStyle}>{t('challenges.resultsPending')}</Text>}
            {(results.data?.winners ?? [])
              .filter((winner) => winner.status !== 'revoked')
              .map((winner) => (
                <Text key={winner.id} style={textStyle} testID={`challenge-winner-${winner.id}`}>
                  {t('challenges.winnerLine', {
                    rank: winner.rank,
                    name: winner.team?.name ?? winner.user?.display_name ?? '—',
                  })}
                  {winner.status === 'provisional' ? ` (${t('challenges.provisional')})` : ''}
                </Text>
              ))}
            {published && (results.data?.winners ?? []).length === 0 ? (
              <Text style={mutedStyle}>{t('challenges.noWinners')}</Text>
            ) : null}
            {!published && canJudge && (data.status === 'judging' || data.status === 'active') ? (
              <Button
                label={t('challenges.publishResults')}
                onPress={() => finish.mutate()}
                busy={finish.isPending}
                testID="challenge-publish-results"
              />
            ) : null}
            {finish.isError ? (
              <Notice tone="error">
                {finish.error instanceof ApiProblem && finish.error.code === 'conflict'
                  ? t('challenges.resultsBlocked')
                  : t('user.actionFailed')}
              </Notice>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  loading: { marginTop: 32 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
