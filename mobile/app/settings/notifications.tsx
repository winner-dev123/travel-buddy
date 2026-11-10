import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import {
  fetchPreferences,
  NOTIFICATION_GROUPS,
  type NotificationGroup,
  type Preferences,
  type PreferencesChange,
  preferencesKey,
  pushEnabled,
  updatePreferences,
} from '@/features/account/preferences';
import { PushBanner } from '@/features/push/PushBanner';
import { useAppTheme } from '@/theme/useAppTheme';

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
const GROUPS = Object.keys(NOTIFICATION_GROUPS) as NotificationGroup[];

/** SCR-109 Notification settings: push per kind of activity and quiet hours (NOTIF-003). In-app
 * notifications always arrive; quiet hours only hold push back, in the account's time zone. */
export default function NotificationSettingsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const preferences = useQuery({
    queryKey: preferencesKey,
    queryFn: () => fetchPreferences(getApiClient()),
  });
  const save = useMutation({
    mutationFn: (change: PreferencesChange) => updatePreferences(getApiClient(), change),
    onSuccess: (saved) => queryClient.setQueryData(preferencesKey, saved),
  });
  const data = preferences.data;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('notificationSettings.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <PushBanner />
        {preferences.isPending ? <ActivityIndicator /> : null}
        {preferences.isError ? (
          <Notice tone="error" testID="notification-settings-error">
            {t('notificationSettings.error')}
          </Notice>
        ) : null}
        {save.isError ? (
          <Notice tone="error" testID="notification-settings-save-error">
            {t('user.actionFailed')}
          </Notice>
        ) : null}
        {data ? (
          <>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('notificationSettings.push')}
            </Text>
            {GROUPS.map((group) => (
              <SwitchRow
                key={group}
                label={t(`notificationSettings.groups.${group}`)}
                value={pushEnabled(data, group)}
                onValueChange={(value) =>
                  save.mutate({
                    notification_settings: Object.fromEntries(
                      NOTIFICATION_GROUPS[group].map((type) => [type, { push: value }]),
                    ),
                  })
                }
                testID={`notify-${group}`}
              />
            ))}
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('notificationSettings.alwaysOn')}
            </Text>
            <QuietHoursEditor
              preferences={data}
              busy={save.isPending}
              onChange={(quiet) => save.mutate({ quiet_hours: quiet })}
            />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function QuietHoursEditor({
  preferences,
  busy,
  onChange,
}: {
  preferences: Preferences;
  busy: boolean;
  onChange: (quiet: Preferences['quiet_hours']) => void;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const current = preferences.quiet_hours ?? null;
  const [start, setStart] = useState(current?.start ?? '22:00');
  const [end, setEnd] = useState(current?.end ?? '07:00');
  const valid = HHMM.test(start) && HHMM.test(end) && start !== end;
  const changed = current !== null && (current.start !== start || current.end !== end);

  return (
    <View style={{ gap: theme.spacing[2] }} testID="quiet-hours">
      <SwitchRow
        label={t('notificationSettings.quietHours')}
        value={current !== null}
        onValueChange={(on) => onChange(on && valid ? { start, end } : null)}
        testID="quiet-hours-toggle"
      />
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {t('notificationSettings.quietHoursHint', { zone: preferences.time_zone })}
      </Text>
      {current !== null ? (
        <>
          <View style={styles.row}>
            <View style={styles.fill}>
              <TextField
                label={t('notificationSettings.from')}
                value={start}
                onChangeText={setStart}
                maxLength={5}
                keyboardType="numbers-and-punctuation"
                testID="quiet-start"
              />
            </View>
            <View style={styles.fill}>
              <TextField
                label={t('notificationSettings.to')}
                value={end}
                onChangeText={setEnd}
                maxLength={5}
                keyboardType="numbers-and-punctuation"
                testID="quiet-end"
              />
            </View>
          </View>
          {!valid ? (
            <Notice tone="error" testID="quiet-invalid">
              {t('notificationSettings.quietInvalid')}
            </Notice>
          ) : null}
          {changed ? (
            <Button
              label={t('notificationSettings.saveQuiet')}
              onPress={() => onChange({ start, end })}
              disabled={!valid}
              busy={busy}
              testID="quiet-save"
            />
          ) : null}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', gap: 12 },
});
