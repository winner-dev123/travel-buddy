// req: AUTH-009
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { i18n } from '@/i18n';

import Help from '../app/settings/help';

const mockApi = { get: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null } }));

const openURL = jest.spyOn(Linking, 'openURL');

function config(url: string | null) {
  return {
    legal: {
      terms_version: '2026-11-01',
      privacy_version: '2026-11-01',
      terms_url: 'https://travelbuddy.app/legal/terms',
      privacy_url: 'https://travelbuddy.app/legal/privacy',
      community_guidelines_url: 'https://travelbuddy.app/legal/community-guidelines',
    },
    support: { email: 'support@travelbuddy.app', url },
  };
}

async function renderHelp() {
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
      <QueryClientProvider client={client}>
        <Help />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  mockApi.get.mockReset();
  openURL.mockReset();
  openURL.mockResolvedValue(undefined);
  await i18n.changeLanguage('en');
});

it('drafts a support email with the app version only, never account details', async () => {
  mockApi.get.mockResolvedValueOnce(config(null));
  await renderHelp();
  await fireEvent.press(await screen.findByTestId('help-contact'));

  const url = String(openURL.mock.calls[0]?.[0]);
  expect(url.startsWith('mailto:support@travelbuddy.app?subject=Travel%20Buddy%20support')).toBe(
    true,
  );
  expect(decodeURIComponent(url)).toContain('Travel Buddy 0.1.0 · ios');
  expect(decodeURIComponent(url)).not.toMatch(/@(?!travelbuddy\.app)/); // no user email
  expect(screen.getByTestId('help-email')).toHaveTextContent(
    'You can also write to support@travelbuddy.app.',
  );
  expect(mockApi.get).toHaveBeenCalledWith('/v1/client-config', {
    query: { platform: 'ios', app_version: '0.1.0' },
  });
});

it('shows the address when no mail app can take the draft', async () => {
  mockApi.get.mockResolvedValueOnce(config(null));
  openURL.mockRejectedValueOnce(new Error('no handler'));
  await renderHelp();
  await fireEvent.press(await screen.findByTestId('help-contact'));
  expect(await screen.findByTestId('help-no-mail')).toHaveTextContent(
    'No mail app is set up. Write to support@travelbuddy.app from any email account.',
  );
});

it('links the help centre only once it is published', async () => {
  mockApi.get.mockResolvedValueOnce(config(null));
  await renderHelp();
  await screen.findByTestId('help-contact');
  expect(screen.queryByTestId('help-center')).toBeNull();
  expect(screen.getByTestId('help-version')).toHaveTextContent('Version 0.1.0');
});

it('opens the help centre and the legal documents', async () => {
  mockApi.get.mockResolvedValueOnce(config('https://travelbuddy.app/support'));
  await renderHelp();
  await fireEvent.press(await screen.findByTestId('help-center'));
  await fireEvent.press(screen.getByTestId('help-terms'));
  await fireEvent.press(screen.getByTestId('help-privacy'));
  await fireEvent.press(screen.getByTestId('help-guidelines'));
  await waitFor(() =>
    expect(openURL.mock.calls.map(([url]) => url)).toEqual([
      'https://travelbuddy.app/support',
      'https://travelbuddy.app/legal/terms',
      'https://travelbuddy.app/legal/privacy',
      'https://travelbuddy.app/legal/community-guidelines',
    ]),
  );
});

it('explains a loading failure', async () => {
  mockApi.get.mockRejectedValueOnce(new Error('offline'));
  await renderHelp();
  expect(await screen.findByTestId('help-error')).toBeTruthy();
});
