import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button } from '@/components/Form';
import { formatBytes, offlineKeys } from '@/features/offline/OfflinePackages';
import { listDownloads, removeDownload, type DownloadedPackage } from '@/features/offline/store';
import { useAppTheme } from '@/theme/useAppTheme';

/** Downloads manager: what is stored for offline use, and room to free (OFF-001). */
export default function DownloadsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const downloads = useQuery({ queryKey: offlineKeys.downloads, queryFn: listDownloads });
  const remove = useMutation({
    mutationFn: (entry: DownloadedPackage) => removeDownload(getApiClient(), entry),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: offlineKeys.downloads }),
  });
  const entries = downloads.data ?? [];
  const total = entries.reduce((sum, entry) => sum + entry.total_bytes, 0);

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('offline.downloads') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {downloads.isSuccess && entries.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('offline.empty')}
          </Text>
        ) : null}
        {entries.length > 0 ? (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('offline.used', { size: formatBytes(total) })}
          </Text>
        ) : null}
        {entries.map((entry) => (
          <View
            key={entry.package_id}
            style={[styles.row, { borderColor: theme.colors.divider }]}
            testID={`download-${entry.package_id}`}
          >
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {entry.destination_name}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('offline.pack', { locale: entry.locale, size: formatBytes(entry.total_bytes) })}
              </Text>
            </View>
            <Button
              label={t('offline.remove')}
              variant="secondary"
              onPress={() => remove.mutate(entry)}
              busy={remove.isPending && remove.variables?.package_id === entry.package_id}
              testID={`download-remove-${entry.package_id}`}
            />
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
    paddingVertical: 10,
  },
});
