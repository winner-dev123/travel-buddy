import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { exploreKeys, getTrip, type TripItem } from '@/features/explore/api';
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
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
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
  item: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 8, gap: 2 },
});
