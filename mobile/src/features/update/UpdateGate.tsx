import { useQuery } from '@tanstack/react-query';
import Constants from 'expo-constants';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Linking, Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { APP_INFO_KEY, fetchAppInfo } from '@/auth/session';
import { Button } from '@/components/Form';
import { useAppTheme } from '@/theme/useAppTheme';

/** The store page for this app, when known (iOS needs `ios.appStoreUrl` in app.json). */
export function storeUrl(): string | null {
  if (Platform.OS === 'android') {
    const pkg = Constants.expoConfig?.android?.package;
    return pkg ? `https://play.google.com/store/apps/details?id=${encodeURIComponent(pkg)}` : null;
  }
  return Constants.expoConfig?.ios?.appStoreUrl ?? null;
}

/** SCR-151 Forced update: when the server says this version is no longer supported
 * (`update_required` in `/v1/client-config`), nothing else is shown. A failed or offline check
 * never blocks the app. */
export function UpdateGate({ children }: { children: ReactNode }) {
  const config = useQuery({
    queryKey: APP_INFO_KEY,
    queryFn: () => fetchAppInfo(getApiClient()),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
  if (!config.data?.update_required) return children;
  return <UpdateRequired latest={config.data.latest_version} />;
}

function UpdateRequired({ latest }: { latest?: string }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const url = storeUrl();
  return (
    <SafeAreaView
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
      testID="update-required"
    >
      <View style={[styles.body, { gap: theme.spacing[3], padding: theme.spacing[5] }]}>
        <Text
          accessibilityRole="header"
          style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
        >
          {t('update.title')}
        </Text>
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {latest ? t('update.bodyVersion', { version: latest }) : t('update.body')}
        </Text>
        {url ? (
          <Button
            label={t('update.action')}
            onPress={() => void Linking.openURL(url).catch(() => undefined)}
            testID="update-open-store"
          />
        ) : (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('update.fromStore')}
          </Text>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  body: { flex: 1, justifyContent: 'center' },
});
