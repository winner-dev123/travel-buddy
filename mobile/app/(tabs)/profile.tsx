import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { signOut } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { Button, Notice, TextField } from '@/components/Form';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-100 Profile (Phase 1 slice): account, display name, privacy summary, sign out. */
export default function ProfileScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const status = useSessionStore((state) => state.status);
  const me = useSessionStore((state) => state.me);

  if (status === 'restoring') {
    return (
      <SafeAreaView style={[styles.center, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator color={theme.colors.primary} />
      </SafeAreaView>
    );
  }

  if (status !== 'signed_in' || !me) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <View
          style={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
          testID="profile-signed-out"
        >
          <Text
            accessibilityRole="header"
            style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
          >
            {t('account.signedOutTitle')}
          </Text>
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('account.signedOutBody')}
          </Text>
          <Button
            label={t('account.goToSignIn')}
            onPress={() => router.push('/sign-in')}
            testID="profile-go-to-sign-in"
          />
        </View>
      </SafeAreaView>
    );
  }

  return <SignedInProfile me={me} />;
}

function SignedInProfile({ me }: { me: Me }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const setMe = useSessionStore((state) => state.setMe);
  const [displayName, setDisplayName] = useState(me.profile.display_name);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);

  async function save(): Promise<void> {
    setNotice(null);
    setBusy(true);
    try {
      const updated = await getApiClient().patch<Me>('/v1/users/me', {
        body: { display_name: displayName },
      });
      setMe(updated);
      setNotice({ tone: 'success', text: t('account.saved') });
    } catch (caught) {
      setNotice({ tone: 'error', text: describeAuthError(caught, t) });
    } finally {
      setBusy(false);
    }
  }

  const row = (label: string, value: string, testID: string) => (
    <View style={{ gap: theme.spacing[1] }}>
      <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>{label}</Text>
      <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]} testID={testID}>
        {value}
      </Text>
    </View>
  );

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        keyboardShouldPersistTaps="handled"
        testID="profile-signed-in"
      >
        <Text
          accessibilityRole="header"
          style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
          testID="profile-display-name"
        >
          {me.profile.display_name}
        </Text>
        {row(t('account.handle'), `@${me.profile.handle}`, 'profile-handle')}
        {row(
          t('account.email'),
          `${me.account.email ?? '—'} · ${
            me.account.email_verified ? t('account.verified') : t('account.notVerified')
          }`,
          'profile-email',
        )}
        {notice ? (
          <Notice tone={notice.tone} testID="profile-notice">
            {notice.text}
          </Notice>
        ) : null}
        <TextField
          label={t('account.displayName')}
          value={displayName}
          onChangeText={setDisplayName}
          maxLength={50}
          testID="profile-display-name-input"
        />
        <Button
          label={t('account.save')}
          onPress={() => void save()}
          busy={busy}
          disabled={!displayName.trim() || displayName === me.profile.display_name}
          testID="profile-save"
        />
        <Text
          accessibilityRole="header"
          style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
        >
          {t('account.privacyHeading')}
        </Text>
        <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
          {me.privacy.discovery_enabled ? t('account.discoveryOn') : t('account.discoveryOff')}
        </Text>
        <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
          {me.privacy.search_engine_indexing ? t('account.indexingOn') : t('account.indexingOff')}
        </Text>
        <Button
          variant="secondary"
          label={t('account.signOut')}
          onPress={() => void signOut(getApiClient())}
          testID="profile-sign-out"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
