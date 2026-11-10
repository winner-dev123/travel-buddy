import { useMutation } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { generateItinerary, type GenerateItinerary } from '@/features/explore/api';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const PACES = ['relaxed', 'moderate', 'packed'] as const;
const MAX_DAYS = 21;

function days(start: string, end: string): number {
  return (
    Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1
  );
}

/** SCR-042 AI trip planner: destination, dates, pace and interests (no personal details). */
export default function PlanTripScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const key = useRef(getApiClient().newIdempotencyKey());
  const [destination, setDestination] = useState<DestinationSummary | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [pace, setPace] = useState<(typeof PACES)[number]>('moderate');
  const [interests, setInterests] = useState('');
  const [preferences, setPreferences] = useState('');

  const datesValid =
    DATE.test(start) && DATE.test(end) && days(start, end) >= 1 && days(start, end) <= MAX_DAYS;
  const valid = destination !== null && datesValid;
  const generate = useMutation({
    mutationFn: () => {
      const body: GenerateItinerary = {
        destination_id: destination!.id,
        start_date: start,
        end_date: end,
        pace,
        interests: [
          ...new Set(
            interests
              .split(',')
              .map((item) => item.trim())
              .filter((item) => item.length > 0)
              .map((item) => item.slice(0, 40)),
          ),
        ].slice(0, 15),
        ...(preferences.trim() ? { preferences: preferences.trim() } : {}),
      };
      return generateItinerary(getApiClient(), key.current, body);
    },
    onSuccess: (generation) =>
      router.replace({ pathname: '/trips/review', params: { generation: generation.id } }),
  });
  const error =
    generate.error instanceof ApiProblem && generate.error.code === 'quota_exceeded'
      ? t('planner.quota')
      : generate.error instanceof ApiProblem && generate.error.code === 'ai_unavailable'
        ? t('planner.unavailable')
        : generate.isError
          ? t('user.actionFailed')
          : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('planner.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <DestinationPicker
          value={destination}
          onChange={setDestination}
          testID="plan-destination"
          variant="destination"
        />
        <TextField
          label={t('planner.start')}
          value={start}
          onChangeText={setStart}
          placeholder="2026-12-04"
          autoCorrect={false}
          testID="plan-start"
        />
        <TextField
          label={t('planner.end')}
          value={end}
          onChangeText={setEnd}
          placeholder="2026-12-06"
          autoCorrect={false}
          testID="plan-end"
        />
        {start && end && !datesValid ? (
          <Notice tone="info">{t('planner.datesHint', { max: MAX_DAYS })}</Notice>
        ) : null}
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('planner.pace')}
        </Text>
        <View style={styles.row}>
          {PACES.map((value) => (
            <Pressable
              key={value}
              onPress={() => setPace(value)}
              accessibilityRole="button"
              accessibilityState={{ selected: pace === value }}
              style={[
                styles.chip,
                {
                  borderColor: pace === value ? theme.colors.primary : theme.colors.divider,
                  backgroundColor: pace === value ? theme.colors.primary : 'transparent',
                },
              ]}
              testID={`plan-pace-${value}`}
            >
              <Text
                style={[
                  theme.typography.label,
                  { color: pace === value ? theme.colors.onPrimary : theme.colors.textPrimary },
                ]}
              >
                {t(`planner.paces.${value}`)}
              </Text>
            </Pressable>
          ))}
        </View>
        <TextField
          label={t('planner.interests')}
          value={interests}
          onChangeText={setInterests}
          testID="plan-interests"
        />
        <TextField
          label={t('planner.preferences')}
          hint={t('planner.privacy')}
          value={preferences}
          onChangeText={setPreferences}
          maxLength={500}
          multiline
          testID="plan-preferences"
        />
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button
          label={t('planner.generate')}
          onPress={() => generate.mutate()}
          disabled={!valid}
          busy={generate.isPending}
          testID="plan-generate"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
