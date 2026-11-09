import { Stack, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import { requestDeletion } from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-118 Delete account: 30-day grace period, cancellable by signing in (AUTH-010). */
export default function DeleteAccountScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const [understood, setUnderstood] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef(getApiClient().newIdempotencyKey());

  async function submit(): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      await requestDeletion(getApiClient(), reason, key.current);
      router.back();
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('account.deleteAccount') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {t('account.deleteExplain')}
        </Text>
        <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
          {t('account.deleteGrace')}
        </Text>
        <TextField
          label={t('account.deleteReason')}
          value={reason}
          onChangeText={setReason}
          maxLength={500}
          multiline
          testID="delete-reason"
        />
        <SwitchRow
          label={t('account.deleteConfirm')}
          value={understood}
          onValueChange={setUnderstood}
          testID="delete-understood"
        />
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button
          label={t('account.deleteSubmit')}
          onPress={() => void submit()}
          disabled={!understood}
          busy={busy}
          testID="delete-submit"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
