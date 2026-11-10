import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import {
  exploreKeys,
  getGeneration,
  saveProposalAsTrip,
  type ProposedActivity,
} from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

const POLL_MS = 2500;

/** SCR-043 AI itinerary review: wait for the plan, read it, save it as a trip (AI-002, AI-003). */
export default function ReviewItineraryScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = useRef(getApiClient().newIdempotencyKey());
  const { generation: id } = useLocalSearchParams<{ generation: string }>();

  const generation = useQuery({
    queryKey: exploreKeys.generation(id),
    queryFn: () => getGeneration(getApiClient(), id),
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? POLL_MS : false),
  });
  const save = useMutation({
    mutationFn: () =>
      saveProposalAsTrip(
        getApiClient(),
        key.current,
        generation.data!,
        t('planner.tripTitle', {
          place: generation.data!.result!.itinerary.destination.name,
        }),
      ),
    onSuccess: (trip) => {
      void queryClient.invalidateQueries({ queryKey: exploreKeys.trips });
      router.replace({ pathname: '/trips/[id]', params: { id: trip.id } });
    },
  });

  const data = generation.data;
  const proposal = data?.status === 'succeeded' ? data.result : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('planner.review') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {generation.isError ? <Notice tone="error">{t('planner.failed')}</Notice> : null}
        {data?.status === 'pending' || generation.isLoading ? (
          <View style={styles.center} testID="review-pending">
            <ActivityIndicator color={theme.colors.primary} />
            <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
              {t('planner.planning')}
            </Text>
          </View>
        ) : null}
        {data?.status === 'failed' ? (
          <>
            <Notice tone="error">
              {data.error?.code === 'ai_unavailable'
                ? t('planner.unavailable')
                : t('planner.failed')}
            </Notice>
            <Button label={t('planner.again')} onPress={() => router.replace('/trips/plan')} />
          </>
        ) : null}
        {proposal ? (
          <>
            <Notice tone="info" testID="review-disclaimer">
              {proposal.disclaimer}
            </Notice>
            {proposal.warnings.map((warning) => (
              <Text
                key={warning}
                style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
              >
                {warning}
              </Text>
            ))}
            {proposal.itinerary.days.map((day) => (
              <View key={day.day_index} style={{ gap: theme.spacing[1] }}>
                <Text
                  accessibilityRole="header"
                  style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                >
                  {t('planner.day', { number: day.day_index + 1, date: day.date })}
                </Text>
                {day.theme ? (
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {day.theme}
                  </Text>
                ) : null}
                {day.items.map((item, index) => (
                  <ActivityRow key={`${day.day_index}-${index}`} item={item} />
                ))}
              </View>
            ))}
            {save.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
            <Button
              label={t('planner.save')}
              onPress={() => save.mutate()}
              busy={save.isPending}
              testID="review-save"
            />
            <Button
              label={t('planner.again')}
              variant="secondary"
              onPress={() => router.replace('/trips/plan')}
            />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function ActivityRow({ item }: { item: ProposedActivity }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  return (
    <View style={[styles.item, { borderColor: theme.colors.divider }]}>
      <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
        {[item.suggested_start_time, item.title].filter(Boolean).join(' · ')}
      </Text>
      {item.description ? (
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {item.description}
        </Text>
      ) : null}
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {item.place ? item.place.name : t('planner.unverified')}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { alignItems: 'center', gap: 8, paddingVertical: 24 },
  item: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 8, gap: 2 },
});
