import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import {
  addUpcoming,
  listUpcoming,
  removeUpcoming,
  upcomingKey,
} from '@/features/account/upcoming';
import { searchDestinations } from '@/features/feed/api';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Upcoming trips (LOC-005): destinations I'm going to, so my feed shows them before I land
 * (FEED-001). Not shared with anyone. */
export default function UpcomingTripsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [chosen, setChosen] = useState<DestinationSummary | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const upcoming = useQuery({ queryKey: upcomingKey, queryFn: () => listUpcoming(getApiClient()) });
  const matches = useQuery({
    queryKey: ['destinations', 'search', search],
    queryFn: () => searchDestinations(getApiClient(), search),
    enabled: search.trim().length >= 2 && chosen === null,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: upcomingKey });
  const add = useMutation({
    mutationFn: () =>
      addUpcoming(getApiClient(), {
        destination_id: (chosen as DestinationSummary).id,
        ...(start ? { start_date: start } : {}),
        ...(end ? { end_date: end } : {}),
      }),
    onSuccess: () => {
      setChosen(null);
      setSearch('');
      setStart('');
      setEnd('');
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (selectionId: string) => removeUpcoming(getApiClient(), selectionId),
    onSuccess: refresh,
  });
  const datesValid =
    (start === '' || DATE.test(start)) &&
    (end === '' || DATE.test(end)) &&
    (start === '' || end === '' || start <= end);
  const label = (d: DestinationSummary) => [d.name, d.country_name].filter(Boolean).join(', ');

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('upcoming.title') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {t('upcoming.explain')}
        </Text>
        {upcoming.isPending ? <ActivityIndicator /> : null}
        {upcoming.isError ? <Notice tone="error">{t('upcoming.error')}</Notice> : null}
        {(upcoming.data ?? []).map((entry) => (
          <View
            key={entry.id}
            style={[styles.row, { borderBottomColor: theme.colors.divider }]}
            testID={`upcoming-${entry.id}`}
          >
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {label(entry.destination)}
              </Text>
              {entry.start_date ? (
                <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                  {t('trips.dates', {
                    start: entry.start_date,
                    end: entry.end_date ?? entry.start_date,
                  })}
                </Text>
              ) : null}
            </View>
            <Pressable
              onPress={() => remove.mutate(entry.id)}
              accessibilityRole="button"
              hitSlop={8}
              testID={`upcoming-remove-${entry.id}`}
            >
              <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
                {t('upcoming.remove')}
              </Text>
            </Pressable>
          </View>
        ))}
        <Text
          accessibilityRole="header"
          style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
        >
          {t('upcoming.add')}
        </Text>
        {chosen ? (
          <View style={styles.row}>
            <Text
              style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}
              testID="upcoming-chosen"
            >
              {label(chosen)}
            </Text>
            <Button
              label={t('compose.changePlace')}
              variant="secondary"
              onPress={() => setChosen(null)}
            />
          </View>
        ) : (
          <>
            <TextField
              label={t('compose.searchPlace')}
              value={search}
              onChangeText={setSearch}
              autoCorrect={false}
              testID="upcoming-search"
            />
            {(matches.data ?? []).map((match) => (
              <Pressable
                key={match.id}
                onPress={() => setChosen(match)}
                accessibilityRole="button"
                style={[styles.match, { borderColor: theme.colors.divider }]}
                testID={`upcoming-match-${match.slug}`}
              >
                <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                  {label(match)}
                </Text>
              </Pressable>
            ))}
          </>
        )}
        <View style={styles.row}>
          <View style={styles.fill}>
            <TextField
              label={t('upcoming.from')}
              value={start}
              onChangeText={setStart}
              placeholder="2026-12-04"
              maxLength={10}
              testID="upcoming-start"
            />
          </View>
          <View style={styles.fill}>
            <TextField
              label={t('upcoming.to')}
              value={end}
              onChangeText={setEnd}
              placeholder="2026-12-08"
              maxLength={10}
              testID="upcoming-end"
            />
          </View>
        </View>
        {!datesValid ? (
          <Notice tone="error" testID="upcoming-dates-invalid">
            {t('upcoming.datesInvalid')}
          </Notice>
        ) : null}
        {add.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        <Button
          label={t('upcoming.save')}
          onPress={() => add.mutate()}
          disabled={chosen === null || !datesValid}
          busy={add.isPending}
          testID="upcoming-save"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderBottomWidth: 0,
    paddingVertical: 4,
  },
  match: { borderWidth: 1, borderRadius: 8, padding: 12 },
});
