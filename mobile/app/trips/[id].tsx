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
import { newEdit } from '@/features/trips/editor';
import { ItemEditor } from '@/features/trips/ItemEditor';
import { type TripEditor, useTripEditor } from '@/features/trips/useTripEditor';
import { useAppTheme } from '@/theme/useAppTheme';

const VISIBILITIES: readonly TripVisibility[] = ['private', 'connections', 'public'];

/** SCR-104 Trip detail: days and their items, offline-first editing (TRIP-004), sharing
 * (TRIP-005), replanning. */
export default function TripScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const trip = useQuery({
    queryKey: exploreKeys.trip(id),
    queryFn: () => getTrip(getApiClient(), id),
  });
  const data = trip.data;
  const editor = useTripEditor(data);
  const view = editor.view;
  const meId = useSessionStore((state) => state.me?.account.id);
  const canEdit =
    view !== undefined &&
    (view.owner.id === meId ||
      view.collaborators.some((c) => c.user.id === meId && c.role === 'editor'));
  const [editing, setEditing] = useState<{ dayId: string; item?: TripItem } | null>(null);
  const editingDay = view?.days.find((day) => day.id === editing?.dayId);
  const editingIndex =
    editing?.item && editingDay
      ? editingDay.items.findIndex((other) => other.id === editing.item?.id)
      : -1;
  const move = (direction: 'up' | 'down') => {
    if (!editing?.item || !editingDay || editingIndex < 0) return;
    const items = editingDay.items;
    // `null` puts it first in the day; otherwise it goes right after the given item.
    const after =
      direction === 'up'
        ? editingIndex >= 2
          ? (items[editingIndex - 2]?.id ?? null)
          : null
        : items[editingIndex + 1]?.id;
    if (after === undefined) return;
    editor.edit(newEdit('update', editing.item.id, { after_item_id: after }));
  };

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
            {canEdit ? <EditorStatusLine editor={editor} /> : null}
            {(view ?? data).days.map((day) => (
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
                  <ItemRow
                    key={item.id}
                    item={item}
                    onEdit={canEdit ? () => setEditing({ dayId: day.id, item }) : undefined}
                  />
                ))}
                {canEdit ? (
                  <Pressable
                    onPress={() => setEditing({ dayId: day.id })}
                    accessibilityRole="button"
                    style={styles.add}
                    testID={`trip-add-item-${day.day_index}`}
                  >
                    <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                      {t('tripEditor.add')}
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            ))}
            <Sharing trip={data} />
            <Replan trip={data} />
          </>
        ) : null}
      </ScrollView>
      {editing ? (
        <ItemEditor
          item={editing.item}
          canMoveUp={editingIndex > 0}
          canMoveDown={
            editingDay !== undefined &&
            editingIndex >= 0 &&
            editingIndex < editingDay.items.length - 1
          }
          onSave={(fields) =>
            editor.edit(
              editing.item
                ? newEdit('update', editing.item.id, fields)
                : newEdit('create', null, fields, editing.dayId),
            )
          }
          onDelete={
            editing.item
              ? () => editing.item && editor.edit(newEdit('delete', editing.item.id, {}))
              : undefined
          }
          onMove={move}
          onClose={() => setEditing(null)}
        />
      ) : null}
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

/** Where this device's edits stand: saved, on their way, waiting for a connection, or refused
 * (with a way out), plus edits that someone else's newer change replaced. */
function EditorStatusLine({ editor }: { editor: TripEditor }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  return (
    <View style={{ gap: theme.spacing[2] }}>
      {editor.conflicts > 0 ? (
        <Notice tone="info" testID="trip-edit-conflicts">
          {t('tripEditor.conflicts', { count: editor.conflicts })}
        </Notice>
      ) : null}
      {editor.status === 'saving' ? (
        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          testID="trip-edit-saving"
        >
          {t('tripEditor.saving')}
        </Text>
      ) : null}
      {editor.status === 'offline' ? (
        <Notice tone="info" testID="trip-edit-offline">
          {t('tripEditor.offline', { count: editor.pending })}
        </Notice>
      ) : null}
      {editor.status === 'failed' ? (
        <View style={{ gap: theme.spacing[2] }} testID="trip-edit-failed">
          <Notice tone="error">{t('tripEditor.failed')}</Notice>
          <Button
            label={t('tripEditor.discard')}
            variant="secondary"
            onPress={editor.discard}
            testID="trip-edit-discard"
          />
        </View>
      ) : null}
    </View>
  );
}

function ItemRow({ item, onEdit }: { item: TripItem; onEdit?: () => void }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const details = [
    item.place?.name ?? (item.unverified ? t('planner.unverified') : null),
    item.origin === 'ai' ? t('trips.aiSuggested') : null,
  ].filter(Boolean);
  return (
    <View style={[styles.row, styles.itemRow, { borderBottomColor: theme.colors.divider }]}>
      <Pressable
        disabled={!item.place}
        onPress={() =>
          item.place && router.push({ pathname: '/places/[id]', params: { id: item.place.id } })
        }
        accessibilityRole={item.place ? 'link' : undefined}
        style={[styles.item, styles.fill]}
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
      {onEdit ? (
        <Pressable
          onPress={onEdit}
          accessibilityRole="button"
          accessibilityLabel={t('tripEditor.editA11y', { title: item.title })}
          hitSlop={8}
          testID={`trip-edit-item-${item.id}`}
        >
          <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
            {t('tripEditor.edit')}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
  item: { paddingVertical: 8, gap: 2 },
  itemRow: { borderBottomWidth: StyleSheet.hairlineWidth },
  add: { paddingVertical: 8 },
});
