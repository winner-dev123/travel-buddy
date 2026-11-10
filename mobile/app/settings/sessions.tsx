import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import {
  accountKeys,
  type DeviceSession,
  listSessions,
  revokeSession,
} from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-110 Devices: where I'm signed in, and signing other devices out (AUTH). A revoked device
 * loses access at its next token refresh, within 15 minutes. */
export default function SessionsScreen() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: accountKeys.sessions,
    queryFn: () => listSessions(getApiClient()),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => revokeSession(getApiClient(), id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: accountKeys.sessions }),
  });

  const when = (iso: string) =>
    new Date(iso).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' });
  const name = (session: DeviceSession) =>
    session.device_name ?? t(`sessions.platform.${session.platform}`);
  const confirm = (session: DeviceSession) =>
    Alert.alert(t('sessions.confirmTitle'), t('sessions.confirmBody', { device: name(session) }), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t('sessions.signOut'),
        style: 'destructive',
        onPress: () => revoke.mutate(session.id),
      },
    ]);
  // The current device first, then the most recently used.
  const items = [...(sessions.data ?? [])].sort(
    (a, b) =>
      Number(b.is_current) - Number(a.is_current) || b.last_used_at.localeCompare(a.last_used_at),
  );

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('sessions.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {t('sessions.explain')}
        </Text>
        {sessions.isPending ? <ActivityIndicator /> : null}
        {sessions.isError ? (
          <Notice tone="error" testID="sessions-error">
            {t('sessions.error')}
          </Notice>
        ) : null}
        {revoke.isError ? (
          <Notice tone="error" testID="sessions-revoke-error">
            {t('user.actionFailed')}
          </Notice>
        ) : null}
        {items.map((session) => (
          <View
            key={session.id}
            style={[styles.row, { borderColor: theme.colors.divider }]}
            testID={`session-${session.id}`}
          >
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {name(session)}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {session.is_current
                  ? t('sessions.thisDevice')
                  : t('sessions.lastActive', { when: when(session.last_used_at) })}
                {session.app_version
                  ? ` · ${t('sessions.version', { version: session.app_version })}`
                  : ''}
              </Text>
            </View>
            {session.is_current ? null : (
              <Button
                label={t('sessions.signOut')}
                variant="secondary"
                onPress={() => confirm(session)}
                busy={revoke.isPending && revoke.variables === session.id}
                testID={`session-signout-${session.id}`}
              />
            )}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
  },
});
