import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Notice, TextField } from '@/components/Form';
import {
  challengeKeys,
  FULFILLMENT_NEXT,
  type FulfillmentStatus,
  listFulfillments,
  moveFulfillment,
} from '@/features/challenges/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-088 rewards to deliver (CHAL-015): organizers move real-world rewards through their
 * states and enter the discount code when issuing it. Codes go only to the winner; this screen
 * never shows them back. */
export default function FulfillmentsScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const [codes, setCodes] = useState<Record<string, string>>({});
  const list = useQuery({
    queryKey: challengeKeys.fulfillments(id),
    queryFn: () => listFulfillments(getApiClient(), id),
  });
  const move = useMutation({
    mutationFn: ({ fulfillment, to }: { fulfillment: string; to: FulfillmentStatus }) =>
      moveFulfillment(getApiClient(), id, fulfillment, {
        to_status: to,
        ...(to === 'issued' && codes[fulfillment]?.trim()
          ? { secret: codes[fulfillment]!.trim() }
          : {}),
      }),
    onSuccess: (_, { fulfillment }) => {
      setCodes((current) => ({ ...current, [fulfillment]: '' }));
      void queryClient.invalidateQueries({ queryKey: challengeKeys.fulfillments(id) });
    },
  });
  const error =
    move.error instanceof ApiProblem && move.error.code === 'validation_failed'
      ? t('challenges.fulfill.codeNeeded')
      : move.error instanceof ApiProblem && move.error.code === 'forbidden'
        ? t('challenges.fulfill.platform')
        : move.isError
          ? t('user.actionFailed')
          : null;
  const items = list.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('challenges.fulfill.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {list.isPending ? <ActivityIndicator color={theme.colors.primary} /> : null}
        {error ? <Notice tone="error">{error}</Notice> : null}
        {list.isSuccess && items.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('challenges.fulfill.empty')}
          </Text>
        ) : null}
        {items.map((item) => (
          <View
            key={item.id}
            style={[styles.card, { borderColor: theme.colors.divider, gap: theme.spacing[2] }]}
            testID={`fulfillment-${item.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {item.recipient?.display_name ?? '—'} · {t(`challenges.fulfillment.${item.status}`)}
            </Text>
            {item.status === 'pending' || item.status === 'disputed' ? (
              <TextField
                label={t('challenges.fulfill.code')}
                value={codes[item.id] ?? ''}
                onChangeText={(value) => setCodes((current) => ({ ...current, [item.id]: value }))}
                maxLength={200}
                autoCapitalize="characters"
                autoCorrect={false}
                testID={`fulfillment-code-${item.id}`}
              />
            ) : null}
            <View style={styles.row}>
              {FULFILLMENT_NEXT[item.status].map((to) => (
                <Pressable
                  key={to}
                  accessibilityRole="button"
                  onPress={() => move.mutate({ fulfillment: item.id, to })}
                  style={[styles.chip, { borderColor: theme.colors.primary }]}
                  testID={`fulfillment-${to}-${item.id}`}
                >
                  <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                    {t(`challenges.fulfill.to.${to}`)}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
