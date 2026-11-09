import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Linking, ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { fetchLegalDocuments, register } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import { i18n } from '@/i18n';
import { useAppTheme } from '@/theme/useAppTheme';

const BIRTH_DATE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

/** SCR-002 Age gate and consents (AUTH-008/009). Only the birth year is stored. */
export default function CompleteRegistrationScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const pending = useSessionStore((state) => state.pendingIdToken);
  const legal = useQuery({
    queryKey: ['client-config', 'legal'],
    queryFn: () => fetchLegalDocuments(getApiClient()),
  });
  const [birthDate, setBirthDate] = useState('');
  const [terms, setTerms] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(): Promise<void> {
    setError(null);
    if (!BIRTH_DATE.test(birthDate.trim())) {
      setError(t('registration.errors.birthDateFormat'));
      return;
    }
    if (!terms || !privacy) {
      setError(t('registration.errors.consentsRequired'));
      return;
    }
    if (!legal.data) {
      setError(t('auth.errors.network'));
      return;
    }
    setBusy(true);
    try {
      await register(getApiClient(), {
        birthDate: birthDate.trim(),
        legal: legal.data,
        locale: i18n.language || 'en',
      });
      router.replace('/profile');
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        keyboardShouldPersistTaps="handled"
        testID="complete-registration-screen"
      >
        <Text
          accessibilityRole="header"
          style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
        >
          {t('registration.title')}
        </Text>
        <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
          {t('registration.intro')}
        </Text>
        {!pending ? <Notice tone="error">{t('registration.errors.expired')}</Notice> : null}
        {error ? (
          <Notice tone="error" testID="registration-error">
            {error}
          </Notice>
        ) : null}
        <TextField
          label={t('registration.birthDate')}
          value={birthDate}
          onChangeText={setBirthDate}
          placeholder="1995-05-17"
          keyboardType="numbers-and-punctuation"
          maxLength={10}
          testID="registration-birth-date"
        />
        <SwitchRow
          label={t('registration.acceptTerms')}
          value={terms}
          onValueChange={setTerms}
          testID="registration-terms"
        />
        {legal.data ? (
          <Button
            variant="secondary"
            label={t('registration.readTerms')}
            onPress={() => void Linking.openURL(legal.data.terms_url)}
          />
        ) : null}
        <SwitchRow
          label={t('registration.acceptPrivacy')}
          value={privacy}
          onValueChange={setPrivacy}
          testID="registration-privacy"
        />
        {legal.data ? (
          <Button
            variant="secondary"
            label={t('registration.readPrivacy')}
            onPress={() => void Linking.openURL(legal.data.privacy_url)}
          />
        ) : null}
        <Button
          label={t('registration.submit')}
          onPress={() => void submit()}
          busy={busy || legal.isLoading}
          disabled={!pending}
          testID="registration-submit"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
