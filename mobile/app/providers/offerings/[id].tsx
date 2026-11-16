import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import { listOfferings, providerKeys, setOfferingLive } from '@/features/providers/api';
import { formatPrice } from '@/features/providers/format';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-169 The provider's offerings in every status: create, edit, publish, take down. */
export default function ManageOfferingsScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <ManageOfferings />
    </ServerFeature>
  );
}

function ManageOfferings() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const offerings = useQuery({
    queryKey: providerKeys.offerings(id, true),
    queryFn: () => listOfferings(getApiClient(), id, true),
  });
  const live = useMutation({
    mutationFn: ({ offeringId, on }: { offeringId: string; on: boolean }) =>
      setOfferingLive(getApiClient(), offeringId, on),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ['providers', 'offerings', id] }),
  });
  const problem =
    live.error instanceof ApiProblem
      ? live.error.code === 'provider_not_approved'
        ? t('providers.offeringsAdmin.notApproved')
        : live.error.code === 'offering_limit_reached'
          ? t('providers.offeringsAdmin.limit')
          : t('providers.actions.failed')
      : null;
  const items = offerings.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.workspace.offerings') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Button
          label={t('providers.offeringsAdmin.new')}
          icon="add-circle-outline"
          onPress={() =>
            router.push({ pathname: '/providers/offering-edit', params: { providerId: id } })
          }
          testID="offerings-new"
        />
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        {offerings.isSuccess && items.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('providers.offeringsAdmin.empty')}
          </Text>
        ) : null}
        {items.map((offering) => (
          <View
            key={offering.id}
            style={[styles.row, { borderColor: theme.colors.divider }]}
            testID={`manage-offering-${offering.id}`}
          >
            <Pressable
              style={styles.fill}
              onPress={() =>
                router.push({
                  pathname: '/providers/offering-edit',
                  params: { providerId: id, offeringId: offering.id },
                })
              }
              accessibilityRole="button"
            >
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {offering.title}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {[
                  t(`providers.offeringStatus.${offering.status}`),
                  offering.price_from
                    ? t('providers.from', {
                        price: formatPrice(offering.price_from, i18n.language),
                      })
                    : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
            </Pressable>
            {offering.status === 'draft' || offering.status === 'archived' ? (
              <Button
                label={t('providers.offeringsAdmin.publish')}
                variant="secondary"
                onPress={() => live.mutate({ offeringId: offering.id, on: true })}
                testID={`offering-publish-${offering.id}`}
              />
            ) : offering.status === 'published' ? (
              <Button
                label={t('providers.offeringsAdmin.archive')}
                variant="ghost"
                onPress={() => live.mutate({ offeringId: offering.id, on: false })}
                testID={`offering-archive-${offering.id}`}
              />
            ) : null}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 8,
  },
});
