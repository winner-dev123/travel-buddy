import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Image, ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import { getOffering, providerKeys } from '@/features/providers/api';
import { ProviderCard } from '@/features/providers/components';
import { durationParts, formatPrice } from '@/features/providers/format';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-162 One offering: what it is, the indicative price, and a request about it (PROV-006). */
export default function OfferingScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <OfferingView />
    </ServerFeature>
  );
}

function OfferingView() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const offering = useQuery({
    queryKey: providerKeys.offering(id),
    queryFn: () => getOffering(getApiClient(), id),
  });
  const data = offering.data;
  const duration = data?.duration_minutes ? durationParts(data.duration_minutes) : null;
  const facts = data
    ? [
        t(`providers.offeringKind.${data.kind}`),
        data.destination?.name,
        duration
          ? duration.days
            ? t('providers.days', { count: duration.days })
            : t('providers.duration', { hours: duration.hours, minutes: duration.mins })
          : null,
        data.max_group_size ? t('providers.upTo', { count: data.max_group_size }) : null,
      ].filter(Boolean)
    : [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{ headerShown: true, title: data?.title ?? t('providers.offering') }}
      />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {offering.isError ? <Notice tone="error">{t('providers.offeringMissing')}</Notice> : null}
        {data ? (
          <>
            {data.cover?.status === 'ready' && data.cover.url ? (
              <Image
                source={{ uri: data.cover.url }}
                style={[styles.cover, { borderRadius: theme.radii.md }]}
                accessibilityIgnoresInvertColors
              />
            ) : null}
            <Text
              accessibilityRole="header"
              style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
            >
              {data.title}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {facts.join(' · ')}
            </Text>
            {data.price_from ? (
              <Text
                style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                testID="offering-price"
              >
                {t(
                  data.price_from.unit === 'per_group'
                    ? 'providers.fromPerGroup'
                    : data.price_from.unit === 'per_person'
                      ? 'providers.fromPerPerson'
                      : 'providers.from',
                  { price: formatPrice(data.price_from, i18n.language) },
                )}
              </Text>
            ) : null}
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('providers.priceNote')}
            </Text>
            {data.description ? (
              <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                {data.description}
              </Text>
            ) : null}
            {signedIn && data.status === 'published' ? (
              <Button
                label={t('providers.request.aboutThis')}
                icon="chatbubbles-outline"
                onPress={() =>
                  router.push({
                    pathname: '/providers/request',
                    params: { providerId: data.provider.id, offeringId: data.id },
                  })
                }
                testID="offering-request"
              />
            ) : null}
            <ProviderCard
              provider={data.provider}
              onPress={() =>
                router.push({ pathname: '/providers/[id]', params: { id: data.provider.id } })
              }
            />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  cover: { width: '100%', aspectRatio: 16 / 9 },
});
