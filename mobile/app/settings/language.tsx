import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice } from '@/components/Form';
import { refreshMe } from '@/features/account/api';
import {
  deviceTimeZone,
  fetchPreferences,
  type PreferencesChange,
  preferencesKey,
  updatePreferences,
} from '@/features/account/preferences';
import { i18n, SUPPORTED_LOCALES, type SupportedLocale } from '@/i18n';
import { useSettingsStore } from '@/state/settingsStore';
import { useAppTheme } from '@/theme/useAppTheme';

/** Native names: a language list is read by people who may not read the current UI language. */
const LANGUAGE_NAMES: Record<SupportedLocale, string> = {
  en: 'English',
  es: 'Español',
  'pt-BR': 'Português (Brasil)',
  fr: 'Français',
  de: 'Deutsch',
};

/** SCR-108 Language and region: app language (saved to the account, I18N-002), the time zone
 * used for quiet hours and dates, and distance units. */
export default function LanguageScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const setLocaleOverride = useSettingsStore((state) => state.setLocaleOverride);
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const preferences = useQuery({
    queryKey: preferencesKey,
    queryFn: () => fetchPreferences(getApiClient()),
    enabled: signedIn,
  });
  const save = useMutation({
    mutationFn: (change: PreferencesChange) => updatePreferences(getApiClient(), change),
    onSuccess: (saved) => {
      queryClient.setQueryData(preferencesKey, saved);
      void refreshMe(getApiClient()).catch(() => undefined);
    },
  });
  const chooseLanguage = (locale: SupportedLocale) => {
    setLocaleOverride(locale);
    void i18n.changeLanguage(locale);
    if (signedIn) save.mutate({ ui_locale: locale });
  };
  const data = preferences.data;
  const device = deviceTimeZone();
  const chip = (selected: boolean) => [
    styles.chip,
    {
      borderColor: selected ? theme.colors.primary : theme.colors.divider,
      backgroundColor: selected ? theme.colors.primary : 'transparent',
    },
  ];
  const chipText = (selected: boolean) => [
    theme.typography.label,
    { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
  ];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('languageSettings.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('languageSettings.language')}
        </Text>
        <View style={styles.chips} accessibilityRole="radiogroup">
          {SUPPORTED_LOCALES.map((locale) => {
            const selected = i18n.language === locale;
            return (
              <Pressable
                key={locale}
                onPress={() => chooseLanguage(locale)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                style={chip(selected)}
                testID={`language-${locale}`}
              >
                <Text style={chipText(selected)}>{LANGUAGE_NAMES[locale]}</Text>
              </Pressable>
            );
          })}
        </View>
        {signedIn && preferences.isPending ? <ActivityIndicator /> : null}
        {save.isError ? (
          <Notice tone="error" testID="language-error">
            {t('user.actionFailed')}
          </Notice>
        ) : null}
        {data ? (
          <>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('languageSettings.timeZone')}
            </Text>
            <Text
              style={[theme.typography.body, { color: theme.colors.textPrimary }]}
              testID="time-zone"
            >
              {data.time_zone}
            </Text>
            {device && device !== data.time_zone ? (
              <Button
                label={t('languageSettings.useDeviceZone', { zone: device })}
                variant="secondary"
                onPress={() => save.mutate({ time_zone: device })}
                busy={save.isPending}
                testID="use-device-zone"
              />
            ) : null}
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('languageSettings.timeZoneHint')}
            </Text>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('languageSettings.distance')}
            </Text>
            <View style={styles.chips} accessibilityRole="radiogroup">
              {(['km', 'mi'] as const).map((unit) => (
                <Pressable
                  key={unit}
                  onPress={() => save.mutate({ distance_unit: unit })}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: data.distance_unit === unit }}
                  style={chip(data.distance_unit === unit)}
                  testID={`distance-${unit}`}
                >
                  <Text style={chipText(data.distance_unit === unit)}>
                    {t(`languageSettings.units.${unit}`)}
                  </Text>
                </Pressable>
              ))}
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
