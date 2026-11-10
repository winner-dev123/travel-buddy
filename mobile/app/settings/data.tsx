import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import {
  accountKeys,
  type DataRequest,
  listDataRequests,
  requestDataExport,
} from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

const ACTIVE: readonly DataRequest['status'][] = ['received', 'processing'];

/** SCR-113 Your data (BL-6.03; AUTH-011): request an archive of my personal data, follow its
 * progress and download it within 7 days; deletion requests show here too. */
export default function YourDataScreen() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const key = useRef(getApiClient().newIdempotencyKey());
  const requests = useQuery({
    queryKey: accountKeys.dataRequests,
    queryFn: () => listDataRequests(getApiClient()),
  });
  const request = useMutation({
    mutationFn: () => requestDataExport(getApiClient(), key.current),
    onSuccess: () => {
      key.current = getApiClient().newIdempotencyKey();
      void queryClient.invalidateQueries({ queryKey: accountKeys.dataRequests });
    },
  });
  const items = requests.data?.data ?? [];
  const preparing = items.some((item) => item.kind === 'export' && ACTIVE.includes(item.status));
  const error =
    request.error instanceof ApiProblem && request.error.code === 'conflict'
      ? t('account.dataBusy')
      : request.isError
        ? t('user.actionFailed')
        : null;
  const day = (iso: string) => new Date(iso).toLocaleDateString(i18n.language);

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('account.yourData') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {t('account.dataExplain')}
        </Text>
        {preparing ? (
          <Notice tone="info" testID="data-preparing">
            {t('account.dataPreparing')}
          </Notice>
        ) : (
          <Button
            label={t('account.dataRequest')}
            onPress={() => request.mutate()}
            busy={request.isPending}
            testID="data-request"
          />
        )}
        {error ? <Notice tone="error">{error}</Notice> : null}
        {requests.isPending ? <ActivityIndicator color={theme.colors.primary} /> : null}
        {items.map((item) => (
          <View
            key={item.id}
            style={[styles.card, { borderColor: theme.colors.divider, gap: theme.spacing[1] }]}
            testID={`data-request-${item.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {t(`account.dataKinds.${item.kind}`)} · {t(`account.dataStatus.${item.status}`)}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('account.dataRequested', { date: day(item.requested_at) })}
            </Text>
            {item.download ? (
              <Button
                label={t('account.dataDownload', { date: day(item.download.expires_at) })}
                variant="secondary"
                onPress={() => void Linking.openURL(item.download!.url)}
                testID={`data-download-${item.id}`}
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
  card: { borderWidth: 1, borderRadius: 12, padding: 12 },
});
