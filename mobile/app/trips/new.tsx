import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import { createTrip, exploreKeys } from '@/features/explore/api';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** SCR-103 New trip (TRIP-001): a title, a destination and dates; days are filled in the editor. */
export default function NewTripScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [destination, setDestination] = useState<DestinationSummary | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [key] = useState(() => getApiClient().newIdempotencyKey());

  const create = useMutation({
    mutationFn: () =>
      createTrip(getApiClient(), key, {
        title: title.trim() || t('trips.defaultTitle', { place: destination?.name ?? '' }),
        startDate: start,
        endDate: end,
        destinationId: destination?.id ?? '',
      }),
    onSuccess: (trip) => {
      void queryClient.invalidateQueries({ queryKey: exploreKeys.trips });
      router.replace({ pathname: '/trips/[id]', params: { id: trip.id } });
    },
  });
  const datesValid = DATE.test(start) && DATE.test(end) && start <= end;
  const failure =
    create.error instanceof ApiProblem && create.error.code === 'validation_failed'
      ? t('planner.datesHint', { max: 30 })
      : create.error
        ? t('user.actionFailed')
        : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('trips.new') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <TextField
          label={t('trips.titleLabel')}
          value={title}
          onChangeText={setTitle}
          maxLength={100}
          testID="new-trip-title"
        />
        <DestinationPicker
          value={destination}
          onChange={setDestination}
          testID="new-trip-destination"
          variant="destination"
        />
        <TextField
          label={t('planner.start')}
          value={start}
          onChangeText={setStart}
          placeholder="2026-12-04"
          autoCapitalize="none"
          testID="new-trip-start"
        />
        <TextField
          label={t('planner.end')}
          value={end}
          onChangeText={setEnd}
          placeholder="2026-12-06"
          autoCapitalize="none"
          testID="new-trip-end"
        />
        {failure ? <Notice tone="error">{failure}</Notice> : null}
        <Button
          label={t('trips.create')}
          onPress={() => create.mutate()}
          disabled={destination === null || !datesValid}
          busy={create.isPending}
          testID="new-trip-create"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
