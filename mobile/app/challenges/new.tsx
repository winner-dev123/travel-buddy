import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import {
  badgeKey,
  challengeKeys,
  createChallenge,
  type NewChallenge,
} from '@/features/challenges/api';
import { useAppTheme } from '@/theme/useAppTheme';

const DURATIONS = [1, 3, 7] as const;
const POLICIES = ['first_correct', 'all_correct'] as const;
const START_DELAY_MS = 2 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** SCR-087 New challenge (BL-5.08; CHAL-001, CHAL-002, CHAL-006, CHAL-013): a riddle with
 * accepted answers (stored normalized, never shown to members), an optional hint and badge.
 * It is saved as a draft; organizers publish it from the challenge screen. Cash prizes, raffles
 * and paid entry are refused by the server. */
export default function NewChallengeScreen() {
  const { groupId } = useLocalSearchParams<{ groupId: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = useRef(getApiClient().newIdempotencyKey());
  const [title, setTitle] = useState('');
  const [riddle, setRiddle] = useState('');
  const [answers, setAnswers] = useState('');
  const [hint, setHint] = useState('');
  const [days, setDays] = useState<(typeof DURATIONS)[number]>(1);
  const [policy, setPolicy] = useState<(typeof POLICIES)[number]>('first_correct');
  const [attempts, setAttempts] = useState('3');
  const [teams, setTeams] = useState(false);
  const [badge, setBadge] = useState('');

  const accepted = answers
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const create = useMutation({
    mutationFn: () => {
      const starts = new Date(Date.now() + START_DELAY_MS);
      const body: NewChallenge = {
        kind: 'riddle',
        title: title.trim(),
        description: riddle.trim(),
        solving_mode: teams ? 'team' : 'individual',
        validation_method: 'exact',
        accepted_answers: accepted.slice(0, 20),
        hints: hint.trim() ? [{ body: hint.trim() }] : [],
        starts_at: starts.toISOString(),
        ends_at: new Date(starts.getTime() + days * DAY_MS).toISOString(),
        max_attempts: Math.min(20, Math.max(1, Number.parseInt(attempts, 10) || 3)),
        winner_policy: policy,
        rewards: badge.trim()
          ? [
              {
                reward_type: 'badge',
                title: badge.trim(),
                badge_key: badgeKey(badge),
                quantity: policy === 'first_correct' ? 1 : 50,
                fulfillment_owner: 'platform',
              },
            ]
          : [],
      };
      return createChallenge(getApiClient(), groupId, key.current, body);
    },
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: challengeKeys.group(groupId) });
      router.replace({ pathname: '/challenges/[id]', params: { id: created.id } });
    },
  });
  const code = create.error instanceof ApiProblem ? create.error.code : null;
  const error =
    code === 'entitlement_required'
      ? t('challenges.premiumNote')
      : code === 'reward_not_permitted'
        ? t('challenges.prizeNotAllowed')
        : code === 'validation_failed'
          ? t('challenges.invalid')
          : create.isError
            ? t('user.actionFailed')
            : null;
  const valid = title.trim().length >= 3 && riddle.trim().length >= 10 && accepted.length > 0;

  const chip = (selected: boolean) => [
    styles.chip,
    {
      borderColor: selected ? theme.colors.primary : theme.colors.divider,
      backgroundColor: selected ? theme.colors.primary : 'transparent',
    },
  ];
  const chipText = (selected: boolean) => [
    theme.typography.label,
    { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
  ];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('challenges.new') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <TextField
          label={t('challenges.form.title')}
          value={title}
          onChangeText={setTitle}
          maxLength={100}
          testID="new-challenge-title"
        />
        <TextField
          label={t('challenges.form.riddle')}
          value={riddle}
          onChangeText={setRiddle}
          maxLength={4000}
          multiline
          testID="new-challenge-riddle"
        />
        <TextField
          label={t('challenges.form.answers')}
          hint={t('challenges.form.answersHint')}
          value={answers}
          onChangeText={setAnswers}
          multiline
          autoCorrect={false}
          testID="new-challenge-answers"
        />
        <TextField
          label={t('challenges.form.hint')}
          value={hint}
          onChangeText={setHint}
          maxLength={500}
          testID="new-challenge-hint"
        />
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('challenges.form.duration')}
        </Text>
        <View style={styles.row}>
          {DURATIONS.map((value) => (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: days === value }}
              onPress={() => setDays(value)}
              style={chip(days === value)}
              testID={`new-challenge-days-${value}`}
            >
              <Text style={chipText(days === value)}>
                {t('challenges.form.days', { count: value })}
              </Text>
            </Pressable>
          ))}
        </View>
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('challenges.form.winners')}
        </Text>
        <View style={styles.row}>
          {POLICIES.map((value) => (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: policy === value }}
              onPress={() => setPolicy(value)}
              style={chip(policy === value)}
              testID={`new-challenge-policy-${value}`}
            >
              <Text style={chipText(policy === value)}>{t(`challenges.policies.${value}`)}</Text>
            </Pressable>
          ))}
        </View>
        <TextField
          label={t('challenges.form.attempts')}
          value={attempts}
          onChangeText={setAttempts}
          keyboardType="number-pad"
          testID="new-challenge-attempts"
        />
        <SwitchRow
          label={t('challenges.form.teams')}
          value={teams}
          onValueChange={setTeams}
          testID="new-challenge-teams"
        />
        <TextField
          label={t('challenges.form.badge')}
          hint={t('challenges.form.badgeHint')}
          value={badge}
          onChangeText={setBadge}
          maxLength={80}
          testID="new-challenge-badge"
        />
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button
          label={t('challenges.form.save')}
          onPress={() => create.mutate()}
          disabled={!valid}
          busy={create.isPending}
          testID="new-challenge-save"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
