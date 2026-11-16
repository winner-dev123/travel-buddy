import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, Text, View } from 'react-native';

import { getApiClient } from '@/api';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

import { listProviders, providerKeys } from './api';
import { ProviderCard } from './components';

const SHOWN = 3;

/** "Local guides & companies" on a destination (PROV-008): hidden when nobody serves it. */
export function LocalProviders({ destination }: { destination: DestinationSummary }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const providers = useQuery({
    queryKey: providerKeys.list(destination.id, null),
    queryFn: () => listProviders(getApiClient(), { destinationId: destination.id, limit: 20 }),
  });
  const items = providers.data?.data ?? [];
  if (items.length === 0) return null;
  return (
    <View style={{ gap: theme.spacing[2] }} testID="local-providers">
      <View
        style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}
      >
        <Text
          accessibilityRole="header"
          style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
        >
          {t('providers.local', { place: destination.name })}
        </Text>
        <Pressable
          onPress={() =>
            router.push({
              pathname: '/providers',
              params: { destinationId: destination.id, place: destination.name },
            })
          }
          accessibilityRole="link"
          hitSlop={8}
          testID="local-providers-all"
        >
          <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
            {t('providers.seeAll')}
          </Text>
        </Pressable>
      </View>
      {items.slice(0, SHOWN).map((provider) => (
        <ProviderCard
          key={provider.id}
          provider={provider}
          onPress={() => router.push({ pathname: '/providers/[id]', params: { id: provider.id } })}
        />
      ))}
    </View>
  );
}
