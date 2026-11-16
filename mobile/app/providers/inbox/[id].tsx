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
import { listInbox, providerKeys, type InquiryStatus } from '@/features/providers/api';
import { RequestCard } from '@/features/providers/components';
import { useAppTheme } from '@/theme/useAppTheme';

const FILTERS: (InquiryStatus | null)[] = ['open', 'accepted', null];

/** SCR-171 The provider's request inbox, shared by the whole team (PROV-010). */
export default function InboxScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <Inbox />
    </ServerFeature>
  );
}

function Inbox() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [status, setStatus] = useState<InquiryStatus | null>('open');
  const inbox = useQuery({
    queryKey: providerKeys.inbox(id, status),
    queryFn: () => listInbox(getApiClient(), id, status),
  });
  const items = inbox.data?.data ?? [];
  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.workspace.inbox') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[2] }}>
        <View style={styles.chips}>
          {FILTERS.map((value) => (
            <Chip
              key={value ?? 'all'}
              label={value ? t(`providers.status.${value}`) : t('providers.filterAll')}
              selected={status === value}
              onPress={() => setStatus(value)}
              testID={`inbox-filter-${value ?? 'all'}`}
            />
          ))}
        </View>
        {inbox.isError ? <Notice tone="error">{t('providers.loadFailed')}</Notice> : null}
        {inbox.isSuccess && items.length === 0 ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="inbox-empty"
          >
            {t('providers.inboxEmpty')}
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

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
