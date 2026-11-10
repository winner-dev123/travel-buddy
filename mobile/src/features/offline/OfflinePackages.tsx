import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { StyleSheet, Text, View } from 'react-native';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

import {
  downloadPackage,
  listDownloads,
  listPackages,
  removeDownload,
  type DownloadedPackage,
  type OfflinePackageSummary,
} from './store';

export const offlineKeys = {
  downloads: ['offline', 'downloads'] as const,
  packages: (destinationId: string) => ['offline', 'packages', destinationId] as const,
};

export function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Download a destination's packs for offline use, or remove them (OFF-001, OFF-004). */
export function OfflinePackages({ destination }: { destination: DestinationSummary }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const packages = useQuery({
    queryKey: offlineKeys.packages(destination.id),
    queryFn: () => listPackages(getApiClient(), destination.id),
  });
  const downloads = useQuery({ queryKey: offlineKeys.downloads, queryFn: listDownloads });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: offlineKeys.downloads });
  const download = useMutation({
    mutationFn: (pkg: OfflinePackageSummary) =>
      downloadPackage(getApiClient(), pkg, destination.name),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (entry: DownloadedPackage) => removeDownload(getApiClient(), entry),
    onSuccess: refresh,
  });
  const error =
    download.error instanceof ApiProblem && download.error.code === 'quota_exceeded'
      ? t('offline.quota')
      : download.error instanceof ApiProblem && download.error.code === 'entitlement_required'
        ? t('offline.premium')
        : download.isError
          ? t('offline.failed')
          : null;

  if (!packages.data || packages.data.length === 0) {
    return null;
  }
  return (
    <View style={{ gap: theme.spacing[2] }} testID="offline-packages">
      <Text
        accessibilityRole="header"
        style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
      >
        {t('offline.title')}
      </Text>
      {packages.data.map((pkg) => {
        const local = (downloads.data ?? []).find((entry) => entry.package_id === pkg.id);
        return (
          <View key={pkg.id} style={styles.row}>
            <Text style={[theme.typography.body, styles.fill, { color: theme.colors.textPrimary }]}>
              {t('offline.pack', { locale: pkg.locale, size: formatBytes(pkg.total_bytes) })}
            </Text>
            {local ? (
              <Button
                label={t('offline.remove')}
                variant="secondary"
                onPress={() => remove.mutate(local)}
                busy={remove.isPending}
                testID={`offline-remove-${pkg.id}`}
              />
            ) : (
              <Button
                label={pkg.entitled ? t('offline.download') : t('offline.premium')}
                onPress={() => download.mutate(pkg)}
                disabled={!pkg.entitled}
                busy={download.isPending && download.variables?.id === pkg.id}
                testID={`offline-download-${pkg.id}`}
              />
            )}
          </View>
        );
      })}
      {error ? <Notice tone="error">{error}</Notice> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  fill: { flex: 1 },
});
