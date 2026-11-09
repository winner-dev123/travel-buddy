import { Stack, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, TextField } from '@/components/Form';
import { updateProfile } from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

const BIO_MAX = 300;

/** SCR-101 Edit profile: display name and bio. */
export default function EditProfileScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const me = useSessionStore((state) => state.me);
  const [displayName, setDisplayName] = useState(me?.profile.display_name ?? '');
  const [bio, setBio] = useState(me?.profile.bio ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!me) return null;
  const changed =
    displayName.trim() !== me.profile.display_name || (bio.trim() || null) !== me.profile.bio;

  async function save(): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      await updateProfile(getApiClient(), {
        display_name: displayName.trim(),
        bio: bio.trim() || null,
      });
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
      <Stack.Screen options={{ headerShown: true, title: t('account.editProfile') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        keyboardShouldPersistTaps="handled"
      >
        <TextField
          label={t('account.displayName')}
          value={displayName}
          onChangeText={setDisplayName}
          maxLength={50}
          testID="profile-display-name-input"
        />
        <TextField
          label={t('account.bio')}
          value={bio}
          onChangeText={setBio}
          maxLength={BIO_MAX}
          multiline
          hint={t('account.bioHint', { count: BIO_MAX - bio.length })}
          testID="profile-bio-input"
        />
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button
          label={t('account.save')}
          onPress={() => void save()}
          busy={busy}
          disabled={!displayName.trim() || !changed}
          testID="profile-save"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
