import { useMutation, useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, TextField } from '@/components/Form';
import { exploreKeys, getTrip, replanTrip, type Trip, type TripItem } from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-104 Trip detail: days and their items (editing arrives with the itinerary editor). */
export default function TripScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const trip = useQuery({
    queryKey: exploreKeys.trip(id),
    queryFn: () => getTrip(getApiClient(), id),
  });
  const data = trip.data;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: data?.title ?? t('trips.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {trip.isError ? <Notice tone="error">{t('trips.missing')}</Notice> : null}
        {data ? (
          <>
            <Text
              accessibilityRole="header"
              style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
            >
              {data.title}
            </Text>
            <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
              {t('trips.dates', { start: data.start_date, end: data.end_date })}
            </Text>
            {data.days.map((day) => (
              <View key={day.id} style={{ gap: theme.spacing[1] }}>
                <Text
                  accessibilityRole="header"
                  style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                >
                  {t('planner.day', { number: day.day_index + 1, date: day.date ?? '' })}
                </Text>
                {day.items.length === 0 ? (
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {t('trips.freeDay')}
                  </Text>
                ) : null}
                {day.items.map((item) => (
                  <ItemRow key={item.id} item={item} />
                ))}
              </View>
            ))}
            <Replan trip={data} />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

/** Ask the assistant to change some days (AI-005, premium); the review applies the proposal. */
function Replan({ trip }: { trip: Trip }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const key = useRef(getApiClient().newIdempotencyKey());
  const premium = useSessionStore(
    (state) => state.me?.entitlements?.features?.['ai.trip_replan'] ?? false,
  );
  const [instruction, setInstruction] = useState('');
  const [days, setDays] = useState<number[]>([]);
  const replan = useMutation({
    mutationFn: () =>
      replanTrip(getApiClient(), key.current, trip.id, {
        instruction: instruction.trim(),
        base_version: trip.version,
        ...(days.length ? { day_indexes: days } : {}),
      }),
    onSuccess: (generation) =>
      router.push({
        pathname: '/trips/review',
        params: { generation: generation.id, trip: trip.id },
      }),
  });
  const error =
    replan.error instanceof ApiProblem && replan.error.code === 'conflict'
      ? t('trips.replanConflict')
      : replan.error instanceof ApiProblem && replan.error.code === 'quota_exceeded'
        ? t('planner.quota')
        : replan.isError
          ? t('user.actionFailed')
          : null;

  return (
    <View style={{ gap: theme.spacing[2] }} testID="trip-replan">
      <Text
        accessibilityRole="header"
        style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
      >
        {t('trips.replanTitle')}
      </Text>
      {!premium ? (
        <Notice tone="info">{t('trips.replanPremium')}</Notice>
      ) : (
        <>
          <TextField
            label={t('trips.replanInstruction')}
            value={instruction}
            onChangeText={setInstruction}
            maxLength={500}
            multiline
            testID="trip-replan-instruction"
          />
          <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
            {t('trips.replanDays')}
          </Text>
          <View style={styles.chips}>
            {trip.days.map((day) => {
              const selected = days.includes(day.day_index);
              return (
                <Pressable
                  key={day.id}
                  onPress={() =>
                    setDays((current) =>
                      selected
                        ? current.filter((index) => index !== day.day_index)
                        : [...current, day.day_index].sort((a, b) => a - b),
                    )
                  }
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  style={[
                    styles.chip,
                    {
                      borderColor: selected ? theme.colors.primary : theme.colors.divider,
                      backgroundColor: selected ? theme.colors.primary : 'transparent',
                    },
                  ]}
                  testID={`trip-replan-day-${day.day_index}`}
                >
                  <Text
                    style={[
                      theme.typography.label,
                      { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
                    ]}
                  >
                    {t('trips.dayShort', { number: day.day_index + 1 })}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          {error ? <Notice tone="error">{error}</Notice> : null}
          <Button
            label={t('trips.replanSubmit')}
            onPress={() => replan.mutate()}
            disabled={instruction.trim().length < 3}
            busy={replan.isPending}
            testID="trip-replan-submit"
          />
        </>
      )}
    </View>
  );
}

function ItemRow({ item }: { item: TripItem }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const details = [
    item.place?.name ?? (item.unverified ? t('planner.unverified') : null),
    item.origin === 'ai' ? t('trips.aiSuggested') : null,
  ].filter(Boolean);
  return (
    <Pressable
      disabled={!item.place}
      onPress={() =>
        item.place && router.push({ pathname: '/places/[id]', params: { id: item.place.id } })
      }
      accessibilityRole={item.place ? 'link' : undefined}
      style={[styles.item, { borderColor: theme.colors.divider }]}
      testID={`trip-item-${item.id}`}
    >
      <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
        {[item.start_time, item.title].filter(Boolean).join(' · ')}
      </Text>
      {details.length ? (
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {details.join(' · ')}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
  item: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 8, gap: 2 },
});
