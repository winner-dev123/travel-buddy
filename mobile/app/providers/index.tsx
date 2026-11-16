import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Chip } from '@/components/Chip';
import { Notice } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import { listProviders, providerKeys, type ProviderKind } from '@/features/providers/api';
import { ProviderCard } from '@/features/providers/components';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-160 Local guides and companies serving a destination (PROV-007). */
export default function ProvidersScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <Providers />
    </ServerFeature>
  );
}

function Providers() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const { destinationId, place } = useLocalSearchParams<{
    destinationId?: string;
    place?: string;
  }>();
  const [kind, setKind] = useState<ProviderKind | null>(null);
  const providers = useQuery({
    queryKey: providerKeys.list(destinationId ?? null, kind),
    queryFn: () => listProviders(getApiClient(), { destinationId, kind, limit: 50 }),
  });
  const items = providers.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: place ? t('providers.local', { place }) : t('providers.title'),
        }}
      />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
          {t('providers.intro')}
        </Text>
        <View style={styles.chips}>
          <Chip
            label={t('providers.filterAll')}
            selected={kind === null}
            onPress={() => setKind(null)}
            testID="providers-kind-all"
          />
          {(['guide', 'company'] as const).map((value) => (
            <Chip
              key={value}
              label={t(`providers.kindPlural.${value}`)}
              selected={kind === value}
              onPress={() => setKind(value)}
              testID={`providers-kind-${value}`}
            />
          ))}
        </View>
        {providers.isError ? <Notice tone="error">{t('providers.loadFailed')}</Notice> : null}
        {providers.isSuccess && items.length === 0 ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="providers-empty"
          >
            {t('providers.empty')}
          </Text>
        ) : null}
        {items.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            onPress={() =>
              router.push({ pathname: '/providers/[id]', params: { id: provider.id } })
            }
          />
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
