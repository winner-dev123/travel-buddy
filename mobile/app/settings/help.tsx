import { useQuery } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Linking,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { APP_VERSION, fetchAppInfo } from '@/auth/session';
import { Notice } from '@/components/Form';
import { MenuRow } from '@/components/MenuRow';
import { useAppTheme } from '@/theme/useAppTheme';

const APP_INFO_KEY = ['client-config', 'app-info'] as const;

/** Help & legal (store readiness: a support contact inside the app, App Store 1.5). The mail
 * draft names the app version and platform only, never account details. */
export default function HelpScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const [mailFailed, setMailFailed] = useState(false);
  const info = useQuery({ queryKey: APP_INFO_KEY, queryFn: () => fetchAppInfo(getApiClient()) });

  const open = (url: string) => void Linking.openURL(url).catch(() => undefined);
  const writeToSupport = (email: string) => {
    setMailFailed(false);
    const signature = `\n\n—\nTravel Buddy ${APP_VERSION} · ${Platform.OS} ${String(Platform.Version)}`;
    const url =
      `mailto:${email}?subject=${encodeURIComponent(t('help.mailSubject'))}` +
      `&body=${encodeURIComponent(signature)}`;
    Linking.openURL(url).catch(() => setMailFailed(true)); // no mail app: show the address
  };

  const heading = [theme.typography.label, { color: theme.colors.textSecondary }];
  const data = info.data;
  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('help.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {info.isPending ? <ActivityIndicator /> : null}
        {info.isError ? (
          <Notice tone="error" testID="help-error">
            {t('help.error')}
          </Notice>
        ) : null}
        {data ? (
          <>
            <Text style={heading}>{t('help.getHelp')}</Text>
            <View>
              <MenuRow
                icon="mail-outline"
                label={t('help.contact')}
                onPress={() => writeToSupport(data.support.email)}
                testID="help-contact"
              />
              {data.support.url ? (
                <MenuRow
                  icon="help-circle-outline"
                  label={t('help.center')}
                  onPress={() => open(data.support.url as string)}
                  testID="help-center"
                />
              ) : null}
            </View>
            <Text
              selectable
              style={[theme.typography.body, { color: theme.colors.textPrimary }]}
              testID="help-email"
            >
              {t('help.emailUs', { email: data.support.email })}
            </Text>
            {mailFailed ? (
              <Notice tone="info" testID="help-no-mail">
                {t('help.noMailApp', { email: data.support.email })}
              </Notice>
            ) : null}
            <Text style={heading}>{t('help.legal')}</Text>
            <View>
              <MenuRow
                icon="document-text-outline"
                label={t('help.terms')}
                onPress={() => open(data.legal.terms_url)}
                testID="help-terms"
              />
              <MenuRow
                icon="shield-checkmark-outline"
                label={t('help.privacy')}
                onPress={() => open(data.legal.privacy_url)}
                testID="help-privacy"
              />
              {data.legal.community_guidelines_url ? (
                <MenuRow
                  icon="people-outline"
                  label={t('help.guidelines')}
                  onPress={() => open(data.legal.community_guidelines_url as string)}
                  testID="help-guidelines"
                />
              ) : null}
            </View>
          </>
        ) : null}
        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          testID="help-version"
        >
          {t('help.version', { version: APP_VERSION })}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
