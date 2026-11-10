import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, TextField } from '@/components/Form';
import { listConnections } from '@/features/account/api';
import {
  type CollaboratorRole,
  exploreKeys,
  getTrip,
  replanTrip,
  setTripVisibility,
  shareTrip,
  type Trip,
  type TripItem,
  type TripVisibility,
  unshareTrip,
} from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

const VISIBILITIES: readonly TripVisibility[] = ['private', 'connections', 'public'];

/** SCR-104 Trip detail: days and their items, sharing (TRIP-005), replanning. */
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
            <Sharing trip={data} />
            <Replan trip={data} />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

/** Who sees the trip (TRIP-005): the owner picks the visibility and shares it with connections
 * as editors or viewers; a collaborator can leave. */
function Sharing({ trip }: { trip: Trip }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const meId = useSessionStore((state) => state.me?.account.id);
  const owner = trip.owner.id === meId;
  const connections = useQuery({
    queryKey: ['me', 'connections'],
    queryFn: () => listConnections(getApiClient()),
    enabled: owner,
  });
  const saved = (updated: Trip) => queryClient.setQueryData(exploreKeys.trip(trip.id), updated);
  const visibility = useMutation({
    mutationFn: (value: TripVisibility) =>
      setTripVisibility(getApiClient(), trip.id, trip.version, value),
    onSuccess: saved,
  });
  const share = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: CollaboratorRole }) =>
      shareTrip(getApiClient(), trip.id, userId, role),
    onSuccess: saved,
  });
  const remove = useMutation({
    mutationFn: (userId: string) => unshareTrip(getApiClient(), trip.id, userId),
    onSuccess: (_, userId) => {
      if (userId === meId) {
        router.back();
      }
      void queryClient.invalidateQueries({ queryKey: exploreKeys.trip(trip.id) });
    },
  });
  const failed = [visibility, share, remove].find((m) => m.isError)?.error;
  const error =
    failed instanceof ApiProblem && failed.code === 'precondition_failed'
      ? t('trips.shareStale')
      : failed
        ? t('user.actionFailed')
        : null;
  const shared = new Set(trip.collaborators.map((c) => c.user.id));
  const candidates = (connections.data?.data ?? []).filter((c) => !shared.has(c.user.id));
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

  if (!owner) {
    return trip.collaborators.some((c) => c.user.id === meId) ? (
      <Button
        label={t('trips.leave')}
        variant="secondary"
        onPress={() => meId && remove.mutate(meId)}
        busy={remove.isPending}
        testID="trip-leave"
      />
    ) : null;
  }
  return (
    <View style={{ gap: theme.spacing[2] }} testID="trip-sharing">
      <Text
        accessibilityRole="header"
        style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
      >
        {t('trips.shareTitle')}
      </Text>
      <View style={styles.chips}>
        {VISIBILITIES.map((value) => (
          <Pressable
            key={value}
            onPress={() => visibility.mutate(value)}
            accessibilityRole="button"
            accessibilityState={{ selected: trip.visibility === value }}
            style={chip(trip.visibility === value)}
            testID={`trip-visibility-${value}`}
          >
            <Text style={chipText(trip.visibility === value)}>
              {t(`trips.visibility.${value}`)}
            </Text>
          </Pressable>
        ))}
      </View>
      {trip.collaborators.map(({ user, role }) => (
        <View key={user.id} style={styles.row} testID={`trip-collaborator-${user.id}`}>
          <Text style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}>
            {user.display_name}
          </Text>
          <Pressable
            onPress={() =>
              share.mutate({ userId: user.id, role: role === 'editor' ? 'viewer' : 'editor' })
            }
            accessibilityRole="button"
            style={chip(role === 'editor')}
            testID={`trip-role-${user.id}`}
          >
            <Text style={chipText(role === 'editor')}>{t(`trips.roles.${role}`)}</Text>
          </Pressable>
          <Pressable
            onPress={() => remove.mutate(user.id)}
            accessibilityRole="button"
            accessibilityLabel={t('trips.removePerson', { name: user.display_name })}
            testID={`trip-remove-${user.id}`}
          >
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('trips.remove')}
            </Text>
          </Pressable>
        </View>
      ))}
      {candidates.length > 0 ? (
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('trips.addPeople')}
        </Text>
      ) : null}
      {candidates.map(({ user }) => (
        <View key={user.id} style={styles.row}>
          <Text style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}>
            {user.display_name}
          </Text>
          <Pressable
            onPress={() => share.mutate({ userId: user.id, role: 'viewer' })}
            accessibilityRole="button"
            style={chip(false)}
            testID={`trip-add-${user.id}`}
          >
            <Text style={chipText(false)}>{t('trips.add')}</Text>
          </Pressable>
        </View>
      ))}
      {error ? <Notice tone="error">{error}</Notice> : null}
    </View>
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
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
  item: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 8, gap: 2 },
});
