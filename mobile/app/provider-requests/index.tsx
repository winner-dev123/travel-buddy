import { useQuery } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import { listMyRequests, providerKeys } from '@/features/providers/api';
import { RequestCard } from '@/features/providers/components';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-164 Requests I sent to guides and companies (PROV-010). */
export default function MyRequestsScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <MyRequests />
    </ServerFeature>
  );
}

function MyRequests() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const requests = useQuery({
    queryKey: providerKeys.myRequests,
    queryFn: () => listMyRequests(getApiClient()),
  });
  const items = requests.data?.data ?? [];
  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.myRequests') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}>
        {requests.isError ? <Notice tone="error">{t('providers.loadFailed')}</Notice> : null}
        {requests.isSuccess && items.length === 0 ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="my-requests-empty"
          >
            {t('providers.noRequests')}
          </Text>
        ) : null}
        {items.map((inquiry) => (
          <RequestCard
            key={inquiry.id}
            inquiry={inquiry}
            onPress={() =>
              router.push({ pathname: '/provider-requests/[id]', params: { id: inquiry.id } })
            }
          />
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
