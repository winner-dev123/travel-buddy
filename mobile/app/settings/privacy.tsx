import { Stack } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { useSessionStore } from '@/auth/sessionStore';
import { Notice, SwitchRow } from '@/components/Form';
import { updatePrivacy, updateProfile } from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-110 Privacy center (Phase 1 slice): private account and search-engine indexing (PROF-004/008). */
export default function PrivacyScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const me = useSessionStore((state) => state.me);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (!me) return null;
  const isPrivate = me.profile.account_visibility === 'private';

  async function run(change: () => Promise<unknown>): Promise<void> {
    setError(null);
    setSaving(true);
    try {
      await change();
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setSaving(false);
    }
  }

  const explain = (text: string) => (
    <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>{text}</Text>
  );

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('account.privacyHeading') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[6] }}>
        <View style={{ gap: theme.spacing[2] }}>
          <SwitchRow
            label={t('account.privateAccount')}
            value={isPrivate}
            onValueChange={(value) =>
              void run(() =>
                updateProfile(getApiClient(), { account_visibility: value ? 'private' : 'public' }),
              )
            }
            testID="privacy-private-account"
          />
          {explain(t('account.privateAccountHint'))}
        </View>
        <View style={{ gap: theme.spacing[2] }}>
          <SwitchRow
            label={t('account.searchIndexing')}
            value={me.privacy.search_engine_indexing}
            onValueChange={(value) =>
              void run(() => updatePrivacy(getApiClient(), { search_engine_indexing: value }))
            }
            testID="privacy-search-indexing"
          />
          {explain(
            isPrivate ? t('account.searchIndexingPrivate') : t('account.searchIndexingHint'),
          )}
        </View>
        {saving ? explain(t('account.saving')) : null}
        {error ? (
          <Notice tone="error" testID="privacy-error">
            {error}
          </Notice>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
