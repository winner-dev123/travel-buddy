import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Linking, Text, View } from 'react-native';

import { getApiClient } from '@/api';
import { getDeviceId } from '@/auth/session';
import { Button, Notice } from '@/components/Form';
import { pushPermission, registerForPush } from '@/features/push/push';
import { useAppTheme } from '@/theme/useAppTheme';

const PERMISSION_KEY = ['push', 'permission'] as const;

/** Asks for push permission in context, on the Notifications screen, never at launch
 * (store guidelines; NOTIF-002). Offers the OS settings once the user has said no. */
export function PushBanner() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const permission = useQuery({ queryKey: PERMISSION_KEY, queryFn: pushPermission });
  const enable = useMutation({
    mutationFn: async () => registerForPush(getApiClient(), await getDeviceId(), { ask: true }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: PERMISSION_KEY }),
  });

  if (permission.data === 'granted') {
    return enable.data === 'registered' ? (
      <Notice tone="success" testID="push-done">
        {t('notifications.push.done')}
      </Notice>
    ) : null;
  }
  if (permission.data === 'denied') {
    return (
      <View style={{ gap: theme.spacing[2] }} testID="push-denied">
        <Notice tone="info">{t('notifications.push.denied')}</Notice>
        <Button
          label={t('notifications.push.openSettings')}
          variant="secondary"
          onPress={() => void Linking.openSettings()}
          testID="push-settings"
        />
      </View>
    );
  }
  if (permission.data !== 'undetermined') return null;
  return (
    <View style={{ gap: theme.spacing[2] }} testID="push-ask">
      <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
        {t('notifications.push.title')}
      </Text>
      <Button
        label={t('notifications.push.enable')}
        onPress={() => enable.mutate()}
        busy={enable.isPending}
        testID="push-enable"
      />
    </View>
  );
}
