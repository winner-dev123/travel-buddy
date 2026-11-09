import { QueryClientProvider } from '@tanstack/react-query';
import { useLocales } from 'expo-localization';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { restoreSession } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import { i18n } from '@/i18n';
import { resolveSupportedLocale } from '@/i18n/resolveLocale';
import { bindQueryOnlineManager } from '@/offline/connectivity';
import { createQueryClient } from '@/query/queryClient';
import { useSettingsStore } from '@/state/settingsStore';
import { useAppTheme } from '@/theme/useAppTheme';

export default function RootLayout() {
  const [queryClient] = useState(createQueryClient);
  const theme = useAppTheme();
  const localeOverride = useSettingsStore((state) => state.localeOverride);
  // Re-renders when the OS language changes while the app is running.
  const deviceLocales = useLocales();
  const deviceLocale = resolveSupportedLocale(deviceLocales.map((locale) => locale.languageTag));

  useEffect(() => bindQueryOnlineManager(), []);

  // Resume the platform session from the refresh token in secure storage (ADR-0003).
  useEffect(() => {
    if (useSessionStore.getState().status === 'restoring') {
      void Promise.resolve()
        .then(() => restoreSession(getApiClient()))
        .catch(() => useSessionStore.getState().setSignedOut());
    }
  }, []);

  useEffect(() => {
    const target = localeOverride ?? deviceLocale;
    if (i18n.language !== target) {
      void i18n.changeLanguage(target);
    }
  }, [localeOverride, deviceLocale]);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: theme.colors.background },
          }}
        >
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="(auth)" options={{ presentation: 'modal' }} />
          <Stack.Screen name="(onboarding)" />
          <Stack.Screen name="+not-found" />
        </Stack>
        <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
