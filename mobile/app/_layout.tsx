import { QueryClientProvider } from '@tanstack/react-query';
import { useLocales } from 'expo-localization';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, type Theme } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo, useState } from 'react';
import { Appearance, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { getApiClient, setAccessTokenRefresher } from '@/api';
import { refreshAccessToken, restoreSession } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import { usePush } from '@/features/push/usePush';
import { ActionSheetHost } from '@/components/ActionSheet';
import { UpdateGate } from '@/features/update/UpdateGate';
import { i18n, SUPPORTED_LOCALES, type SupportedLocale } from '@/i18n';
import { useLaunchScreen } from '@/launch/launchScreen';
import { resolveSupportedLocale } from '@/i18n/resolveLocale';
import { bindQueryOnlineManager } from '@/offline/connectivity';
import { createQueryClient, refetchWhenForegrounded } from '@/query/queryClient';
import { useSettingsStore } from '@/state/settingsStore';
import { hydrateUiPreferences } from '@/state/uiPreferences';
import { useAppFonts } from '@/theme/fonts';
import { useAppTheme } from '@/theme/useAppTheme';

export default function RootLayout() {
  const [queryClient] = useState(createQueryClient);
  // The saved appearance is applied before the first frame, so the app never opens in the
  // wrong theme and then switches.
  useState(hydrateUiPreferences);
  const theme = useAppTheme();
  const fontsReady = useAppFonts();
  useLaunchScreen(fontsReady);
  const themePreference = useSettingsStore((state) => state.themePreference);
  const localeOverride = useSettingsStore((state) => state.localeOverride);
  // The language saved to the account (I18N-002) wins over the device's after a restart.
  const accountLocale = useSessionStore((state) => state.me?.preferences.ui_locale);
  const savedLocale = SUPPORTED_LOCALES.includes(accountLocale as SupportedLocale)
    ? (accountLocale as SupportedLocale)
    : null;
  // Re-renders when the OS language changes while the app is running.
  const deviceLocales = useLocales();
  const deviceLocale = resolveSupportedLocale(deviceLocales.map((locale) => locale.languageTag));

  // Native surfaces (keyboard, pickers, system dialogs) follow the app's appearance too.
  useEffect(() => {
    Appearance.setColorScheme(themePreference === 'system' ? 'unspecified' : themePreference);
  }, [themePreference]);

  // Navigation chrome (headers, the tab bar, the background behind transitions) uses the
  // same tokens as the screens.
  const navigationTheme = useMemo<Theme>(() => {
    const base = theme.scheme === 'dark' ? DarkTheme : DefaultTheme;
    return {
      ...base,
      colors: {
        primary: theme.colors.primary,
        background: theme.colors.background,
        card: theme.colors.background,
        text: theme.colors.textPrimary,
        border: theme.colors.divider,
        notification: theme.colors.danger,
      },
      fonts: {
        regular: { fontFamily: theme.fonts.regular, fontWeight: 'normal' },
        medium: { fontFamily: theme.fonts.medium, fontWeight: 'normal' },
        bold: { fontFamily: theme.fonts.semibold, fontWeight: 'normal' },
        heavy: { fontFamily: theme.fonts.bold, fontWeight: 'normal' },
      },
    };
  }, [theme]);

  useEffect(() => bindQueryOnlineManager(), []);
  useEffect(() => refetchWhenForegrounded(), []);
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

  if (!fontsReady) {
    // A few frames at most: the typefaces ship inside the app.
    return <View style={{ flex: 1, backgroundColor: theme.colors.background }} />;
  }

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider value={navigationTheme}>
          <UpdateGate>
            <Stack
              screenOptions={{
                headerShown: false,
                contentStyle: { backgroundColor: theme.colors.background },
                headerStyle: { backgroundColor: theme.colors.background },
                headerTintColor: theme.colors.textPrimary,
                headerTitleStyle: { fontFamily: theme.fonts.semibold, fontSize: 17 },
                headerShadowVisible: false,
                headerBackButtonDisplayMode: 'minimal',
              }}
            >
              <Stack.Screen name="(tabs)" />
              <Stack.Screen name="(auth)" options={{ presentation: 'modal' }} />
              <Stack.Screen name="(onboarding)" />
              <Stack.Screen name="post/[id]" />
              <Stack.Screen name="compose" options={{ presentation: 'modal' }} />
              <Stack.Screen name="paywall" options={{ presentation: 'modal' }} />
              <Stack.Screen name="report" options={{ presentation: 'modal' }} />
              <Stack.Screen name="notifications" />
              <Stack.Screen name="user/[id]" />
              <Stack.Screen name="settings/profile" />
              <Stack.Screen name="settings/privacy" />
              <Stack.Screen name="settings/blocked" />
              <Stack.Screen name="settings/delete-account" />
              <Stack.Screen name="settings/appearance" />
              <Stack.Screen name="discovery/consent" options={{ presentation: 'modal' }} />
              <Stack.Screen name="+not-found" />
            </Stack>
          </UpdateGate>
        </ThemeProvider>
        <ActionSheetHost />
        <StatusBar style={theme.scheme === 'dark' ? 'light' : 'dark'} />
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
