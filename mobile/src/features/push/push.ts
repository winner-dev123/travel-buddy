import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import type { ApiClient } from '@/api';

/** Where a notification leads (the same mapping for the inbox and for push taps). */
export type NotificationRoute =
  | {
      pathname: '/post/[id]' | '/user/[id]' | '/chat/[id]' | '/challenges/[id]' | '/groups/[id]';
      params: { id: string };
    }
  | { pathname: '/trips/review'; params: { generation: string } }
  | { pathname: '/settings/data' | '/settings/subscription' }
  | null;

export function notificationRoute(
  entityType: string | null | undefined,
  entityId: string | null | undefined,
): NotificationRoute {
  if (!entityType) return null;
  if (entityType === 'data_request') return { pathname: '/settings/data' }; // export ready
  if (entityType === 'subscription') return { pathname: '/settings/subscription' }; // BILL-011
  if (!entityId) return null;
  if (entityType === 'ai_generation') {
    return { pathname: '/trips/review', params: { generation: entityId } };
  }
  const pathname = (
    {
      post: '/post/[id]',
      user: '/user/[id]',
      conversation: '/chat/[id]',
      challenge: '/challenges/[id]',
      group: '/groups/[id]',
    } as const
  )[entityType as 'post' | 'user' | 'conversation' | 'challenge' | 'group'];
  return pathname ? { pathname, params: { id: entityId } } : null;
}

export type PushState = 'granted' | 'undetermined' | 'denied';

export async function pushPermission(): Promise<PushState> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return 'granted';
  return current.canAskAgain ? 'undetermined' : 'denied';
}

/** The EAS project the Expo push service needs; absent in plain development builds. */
function projectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  return extra?.eas?.projectId ?? Constants.easConfig?.projectId;
}

/** Register this session's push token (NOTIF-002). With ``ask`` the OS prompt may appear; without
 * it, only an existing permission is used (token refresh at start-up). Never throws. */
export async function registerForPush(
  client: ApiClient,
  deviceId: string,
  { ask }: { ask: boolean },
): Promise<'registered' | 'denied' | 'unavailable'> {
  try {
    let state = await pushPermission();
    if (state === 'undetermined' && ask) {
      state = (await Notifications.requestPermissionsAsync()).granted ? 'granted' : 'denied';
    }
    if (state !== 'granted') return 'denied';
    const project = projectId();
    if (!project) return 'unavailable';
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'Travel Buddy',
        // eslint-disable-next-line import/namespace -- re-exported enum the import plugin cannot resolve (tsc does)
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }
    const token = (await Notifications.getExpoPushTokenAsync({ projectId: project })).data;
    await client.post('/v1/users/me/devices', {
      body: { provider: 'expo', token, device_id: deviceId },
    });
    return 'registered';
  } catch {
    return 'unavailable'; // emulators, Expo Go limits, network: try again next start
  }
}
