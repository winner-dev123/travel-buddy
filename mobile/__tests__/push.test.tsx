// req: NOTIF-002, NOTIF-004
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as Notifications from 'expo-notifications';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { PushBanner } from '@/features/push/PushBanner';
import { notificationRoute, registerForPush } from '@/features/push/push';
import { i18n } from '@/i18n';

const mockApi = { post: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { extra: { eas: { projectId: 'project-1' } } } },
}));

const permissions = Notifications.getPermissionsAsync as jest.Mock;
const request = Notifications.requestPermissionsAsync as jest.Mock;

async function renderUi(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, refetchInterval: false },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  mockApi.post.mockReset();
  permissions.mockReset();
  request.mockReset();
  await i18n.changeLanguage('en');
});

it('maps notification targets to screens', () => {
  expect(notificationRoute('challenge', 'c1')).toEqual({
    pathname: '/challenges/[id]',
    params: { id: 'c1' },
  });
  expect(notificationRoute('conversation', 'v1')?.pathname).toBe('/chat/[id]');
  expect(notificationRoute('data_request', 'x')).toBeNull();
  expect(notificationRoute(null, null)).toBeNull();
});

it('registers the Expo token only with permission, asking only when told to', async () => {
  permissions.mockResolvedValue({ granted: false, canAskAgain: true });
  expect(await registerForPush(mockApi as never, 'device-1', { ask: false })).toBe('denied');
  expect(request).not.toHaveBeenCalled();
  request.mockResolvedValueOnce({ granted: true });
  expect(await registerForPush(mockApi as never, 'device-1', { ask: true })).toBe('registered');
  expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/devices', {
    body: { provider: 'expo', token: 'ExponentPushToken[test-token]', device_id: 'device-1' },
  });
});

it('asks in context and offers settings after a refusal', async () => {
  permissions.mockResolvedValue({ granted: false, canAskAgain: true });
  request.mockResolvedValueOnce({ granted: true });
  await renderUi(<PushBanner />);
  permissions.mockResolvedValue({ granted: true, canAskAgain: true });
  await fireEvent.press(await screen.findByTestId('push-enable'));
  expect(await screen.findByTestId('push-done')).toBeTruthy();
  await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
});

it('points to the phone settings once notifications were refused', async () => {
  permissions.mockResolvedValue({ granted: false, canAskAgain: false });
  await renderUi(<PushBanner />);
  expect(await screen.findByTestId('push-settings')).toBeTruthy();
  expect(screen.queryByTestId('push-enable')).toBeNull();
});
