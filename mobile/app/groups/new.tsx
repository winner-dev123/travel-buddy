import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import type { DestinationSummary } from '@/features/feed/types';
import { createGroup } from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-092 New group (GRP-001..003): premium only; the server re-checks the entitlement. */
export default function NewGroupScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = useRef(getApiClient().newIdempotencyKey());
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [place, setPlace] = useState<DestinationSummary | null>(null);
  const [capacity, setCapacity] = useState('10');

  const create = useMutation({
    mutationFn: () =>
      createGroup(getApiClient(), key.current, {
        name: name.trim(),
        primary_destination_id: place!.id,
        member_capacity: Math.min(50, Math.max(2, Number.parseInt(capacity, 10) || 10)),
        ...(description.trim() ? { description: description.trim() } : {}),
      }),
    onSuccess: (group) => {
      void queryClient.invalidateQueries({ queryKey: ['groups'] });
      router.replace({ pathname: '/groups/[id]', params: { id: group.id } });
    },
  });
  const needsPremium =
    create.error instanceof ApiProblem && create.error.code === 'entitlement_required';
  const error = needsPremium
    ? t('groups.premiumNote')
    : create.error instanceof ApiProblem && create.error.code === 'quota_exceeded'
      ? t('groups.quota')
      : create.isError
        ? t('user.actionFailed')
        : null;
  const valid = name.trim().length >= 3 && place !== null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('groups.create') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <TextField
          label={t('groups.name')}
          value={name}
          onChangeText={setName}
          maxLength={60}
          testID="group-name"
        />
        <TextField
          label={t('groups.description')}
          value={description}
          onChangeText={setDescription}
          maxLength={1000}
          multiline
          testID="group-description"
        />
        <DestinationPicker
          value={place}
          onChange={setPlace}
          label={t('groups.destination')}
          variant="destination"
          testID="group-destination"
        />
        <TextField
          label={t('groups.capacity')}
          value={capacity}
          onChangeText={setCapacity}
          keyboardType="number-pad"
          testID="group-capacity"
        />
        {error ? <Notice tone="error">{error}</Notice> : null}
        {needsPremium ? (
          <Button
            label={t('paywall.seePremium')}
            variant="secondary"
            icon="diamond-outline"
            onPress={() =>
              router.push({ pathname: '/paywall', params: { reason: 'groups.create' } })
            }
            testID="group-see-premium"
          />
        ) : null}
        <Button
          label={t('groups.create')}
          onPress={() => create.mutate()}
          disabled={!valid}
          busy={create.isPending}
          testID="group-create"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
