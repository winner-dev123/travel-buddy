import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';
import { useEffect } from 'react';

import { getApiClient } from '@/api';
import { getDeviceId } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import { notificationRoute, registerForPush } from '@/features/push/push';

// Show pushes that arrive while the app is open as a banner, without sound (NOTIF-003 quiet
// hours are applied on the server before sending).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

/** Keeps this session's push token registered (only when permission already exists; the prompt
 * lives on the Notifications screen) and opens the right screen when a push is tapped. */
export function usePush(): void {
  const router = useRouter();
  const status = useSessionStore((state) => state.status);

  useEffect(() => {
    if (status !== 'signed_in') return;
    void getDeviceId().then((deviceId) =>
      registerForPush(getApiClient(), deviceId, { ask: false }),
    );
  }, [status]);

  useEffect(() => {
    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as
        { entity_type?: string; entity_id?: string } | undefined;
      const route = notificationRoute(data?.entity_type, data?.entity_id);
      if (route) router.push(route);
    });
    return () => subscription.remove();
  }, [router]);
}
