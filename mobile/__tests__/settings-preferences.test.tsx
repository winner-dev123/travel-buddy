// req: NOTIF-003, I18N-002
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Linking, Platform, Text } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Preferences } from '@/features/account/preferences';
import { UpdateGate } from '@/features/update/UpdateGate';
import { i18n } from '@/i18n';
import { useSettingsStore } from '@/state/settingsStore';

import LanguageScreen from '../app/settings/language';
import NotificationSettings from '../app/settings/notifications';

const mockApi = { get: jest.fn(), patch: jest.fn(), post: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null } }));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { android: { package: 'com.travelbuddy.app' }, ios: {} } },
}));

const openURL = jest.spyOn(Linking, 'openURL');

function preferences(overrides: Partial<Preferences> = {}): Preferences {
  return {
    ui_locale: 'en',
    content_languages: [],
    time_zone: 'Pacific/Chatham',
    currency_code: 'EUR',
    distance_unit: 'km',
    auto_translate: false,
    notification_settings: { post_reaction: { push: false } },
    quiet_hours: null,
    ...overrides,
  };
}

const me = {
  account: {
    id: 'u1',
    email: 'me@example.com',
    email_verified: true,
    status: 'active',
    primary_locale: 'en',
  },
  profile: { id: 'u1', handle: 'me', display_name: 'Me', bio: null, account_visibility: 'public' },
  preferences: { ui_locale: 'en', time_zone: 'Pacific/Chatham' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: true,
} as unknown as Me;

async function renderUi(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
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
  mockApi.get.mockReset();
  mockApi.patch.mockReset();
  openURL.mockReset();
  openURL.mockResolvedValue(undefined);
  useSessionStore.getState().setSignedIn(me);
  useSettingsStore.getState().setLocaleOverride(null);
  await i18n.changeLanguage('en');
});

afterAll(async () => {
  await i18n.changeLanguage('en');
});

describe('notification settings', () => {
  it('turns push off for a kind of activity and keeps what was off', async () => {
    mockApi.get.mockResolvedValue(preferences());
    mockApi.patch.mockImplementation(async (_path: string, { body }: { body: object }) =>
      preferences(body as Partial<Preferences>),
    );
    await renderUi(<NotificationSettings />);
    expect(await screen.findByTestId('notify-stories')).toHaveProp('value', false);
    expect(screen.getByTestId('notify-people')).toHaveProp('value', true);

    await fireEvent(screen.getByTestId('notify-people'), 'valueChange', false);
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me/preferences', {
        body: {
          notification_settings: {
            connection_request: { push: false },
            connection_accepted: { push: false },
            new_follower: { push: false },
            follow_request: { push: false },
          },
        },
      }),
    );
  });

  it('sets quiet hours in the account time zone and validates the times', async () => {
    mockApi.get.mockResolvedValue(preferences());
    mockApi.patch.mockImplementation(async (_path: string, { body }: { body: object }) =>
      preferences(body as Partial<Preferences>),
    );
    await renderUi(<NotificationSettings />);
    expect(await screen.findByTestId('quiet-hours')).toHaveTextContent(/Pacific\/Chatham/);
    await fireEvent(screen.getByTestId('quiet-hours-toggle'), 'valueChange', true);
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenLastCalledWith('/v1/users/me/preferences', {
        body: { quiet_hours: { start: '22:00', end: '07:00' } },
      }),
    );
    await fireEvent.changeText(await screen.findByTestId('quiet-end'), '22:00');
    expect(screen.getByTestId('quiet-invalid')).toBeTruthy(); // start and end must differ
    expect(screen.getByTestId('quiet-save')).toBeDisabled();
    await fireEvent.changeText(screen.getByTestId('quiet-end'), '06:30');
    await fireEvent.press(screen.getByTestId('quiet-save'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenLastCalledWith('/v1/users/me/preferences', {
        body: { quiet_hours: { start: '22:00', end: '06:30' } },
      }),
    );
  });
});

describe('language and region', () => {
  it('switches the app language and saves it to the account', async () => {
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/users/me/preferences' ? preferences() : me,
    );
    mockApi.patch.mockResolvedValue(preferences({ ui_locale: 'es' }));
    await renderUi(<LanguageScreen />);
    await fireEvent.press(await screen.findByTestId('language-es'));
    expect(i18n.language).toBe('es');
    expect(useSettingsStore.getState().localeOverride).toBe('es');
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me/preferences', {
        body: { ui_locale: 'es' },
      }),
    );
  });

  it("offers this phone's time zone and the distance unit", async () => {
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/users/me/preferences' ? preferences() : me,
    );
    mockApi.patch.mockImplementation(async (_path: string, { body }: { body: object }) =>
      preferences(body as Partial<Preferences>),
    );
    const device = Intl.DateTimeFormat().resolvedOptions().timeZone;
    await renderUi(<LanguageScreen />);
    expect(await screen.findByTestId('time-zone')).toHaveTextContent('Pacific/Chatham');
    await fireEvent.press(screen.getByTestId('use-device-zone'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenCalledWith('/v1/users/me/preferences', {
        body: { time_zone: device },
      }),
    );
    await fireEvent.press(await screen.findByTestId('distance-mi'));
    await waitFor(() =>
      expect(mockApi.patch).toHaveBeenLastCalledWith('/v1/users/me/preferences', {
        body: { distance_unit: 'mi' },
      }),
    );
  });
});

describe('forced update', () => {
  const config = (updateRequired: boolean) => ({
    legal: {
      terms_version: '1',
      privacy_version: '1',
      terms_url: 'https://t',
      privacy_url: 'https://p',
    },
    support: { email: 'support@travelbuddy.app', url: null },
    update_required: updateRequired,
    min_supported_version: '0.2.0',
    latest_version: '0.3.0',
  });

  it('blocks an unsupported version and links to the store', async () => {
    const original = Platform.OS;
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    mockApi.get.mockResolvedValue(config(true));
    await renderUi(
      <UpdateGate>
        <Text testID="app-content">app</Text>
      </UpdateGate>,
    );
    expect(await screen.findByTestId('update-required')).toHaveTextContent(/version 0\.3\.0/);
    expect(screen.queryByTestId('app-content')).toBeNull();
    await fireEvent.press(screen.getByTestId('update-open-store'));
    expect(openURL).toHaveBeenCalledWith(
      'https://play.google.com/store/apps/details?id=com.travelbuddy.app',
    );
    Object.defineProperty(Platform, 'OS', { value: original, configurable: true });
  });

  it('never blocks a supported version or a failed check', async () => {
    mockApi.get.mockResolvedValueOnce(config(false));
    await renderUi(
      <UpdateGate>
        <Text testID="app-content">app</Text>
      </UpdateGate>,
    );
    expect(await screen.findByTestId('app-content')).toBeTruthy();
  });

  it('shows the app when the check fails', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('offline'));
    await renderUi(
      <UpdateGate>
        <Text testID="app-content">app</Text>
      </UpdateGate>,
    );
    expect(await screen.findByTestId('app-content')).toBeTruthy();
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(screen.queryByTestId('update-required')).toBeNull();
  });
});
