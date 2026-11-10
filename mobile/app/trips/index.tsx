import { useQuery } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { exploreKeys, listTrips } from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-103 Trips: the trips I own or collaborate on. */
export default function TripsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const trips = useQuery({ queryKey: exploreKeys.trips, queryFn: () => listTrips(getApiClient()) });

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('trips.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Button label={t('explore.plan')} onPress={() => router.push('/trips/plan')} />
        {trips.isError ? <Notice tone="error">{t('trips.loadFailed')}</Notice> : null}
        {trips.data && trips.data.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('trips.empty')}
          </Text>
        ) : null}
        {(trips.data ?? []).map((trip) => (
          <Pressable
            key={trip.id}
            onPress={() => router.push({ pathname: '/trips/[id]', params: { id: trip.id } })}
            accessibilityRole="link"
            accessibilityLabel={trip.title}
            style={[styles.row, { borderColor: theme.colors.divider }]}
            testID={`trip-${trip.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {trip.title}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('trips.dates', { start: trip.start_date, end: trip.end_date })}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 10, gap: 2 },
});
