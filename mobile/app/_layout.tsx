import { QueryClientProvider } from '@tanstack/react-query';
import { useLocales } from 'expo-localization';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { getApiClient, setAccessTokenRefresher } from '@/api';
import { refreshAccessToken, restoreSession } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import { usePush } from '@/features/push/usePush';
import { ActionSheetHost } from '@/components/ActionSheet';
import { UpdateGate } from '@/features/update/UpdateGate';
import { i18n, SUPPORTED_LOCALES, type SupportedLocale } from '@/i18n';
import { resolveSupportedLocale } from '@/i18n/resolveLocale';
import { bindQueryOnlineManager } from '@/offline/connectivity';
import { createQueryClient } from '@/query/queryClient';
import { useSettingsStore } from '@/state/settingsStore';
import { useAppTheme } from '@/theme/useAppTheme';

export default function RootLayout() {
  const [queryClient] = useState(createQueryClient);
  const theme = useAppTheme();
  const localeOverride = useSettingsStore((state) => state.localeOverride);
  // The language saved to the account (I18N-002) wins over the device's after a restart.
  const accountLocale = useSessionStore((state) => state.me?.preferences.ui_locale);
  const savedLocale = SUPPORTED_LOCALES.includes(accountLocale as SupportedLocale)
    ? (accountLocale as SupportedLocale)
    : null;
  // Re-renders when the OS language changes while the app is running.
  const deviceLocales = useLocales();
  const deviceLocale = resolveSupportedLocale(deviceLocales.map((locale) => locale.languageTag));

  useEffect(() => bindQueryOnlineManager(), []);
  usePush();

  // Resume the platform session from the refresh token in secure storage (ADR-0003).
  useEffect(() => {
    setAccessTokenRefresher(() => refreshAccessToken(getApiClient()));
    if (useSessionStore.getState().status === 'restoring') {
      void Promise.resolve()
        .then(() => restoreSession(getApiClient()))
        .catch(() => useSessionStore.getState().setSignedOut());
    }
  }, []);

  useEffect(() => {
    const target = localeOverride ?? savedLocale ?? deviceLocale;
    if (i18n.language !== target) {
      void i18n.changeLanguage(target);
    }
  }, [localeOverride, savedLocale, deviceLocale]);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <UpdateGate>
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: theme.colors.background },
            }}
          >
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="(auth)" options={{ presentation: 'modal' }} />
            <Stack.Screen name="(onboarding)" />
            <Stack.Screen name="post/[id]" />
            <Stack.Screen name="compose" options={{ presentation: 'modal' }} />
            <Stack.Screen name="report" options={{ presentation: 'modal' }} />
            <Stack.Screen name="notifications" />
            <Stack.Screen name="user/[id]" />
            <Stack.Screen name="settings/profile" />
            <Stack.Screen name="settings/privacy" />
            <Stack.Screen name="settings/blocked" />
            <Stack.Screen name="settings/delete-account" />
            <Stack.Screen name="discovery/consent" options={{ presentation: 'modal' }} />
            <Stack.Screen name="+not-found" />
          </Stack>
        </UpdateGate>
        <ActionSheetHost />
        <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
