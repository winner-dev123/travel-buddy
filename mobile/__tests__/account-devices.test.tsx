// req: AUTH-006, BILL-005, PROF-007
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Alert, Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { Entitlements } from '@/features/account/api';
import { i18n } from '@/i18n';

import FollowRequests from '../app/settings/follow-requests';
import Sessions from '../app/settings/sessions';
import Subscription from '../app/settings/subscription';

const mockApi = { get: jest.fn(), delete: jest.fn(), post: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn() }),
  Stack: { Screen: () => null },
}));
jest.mock('expo-constants', () => ({
  __esModule: true,
  default: { expoConfig: { android: { package: 'com.travelbuddy.app' } } },
}));

const openURL = jest.spyOn(Linking, 'openURL');

async function renderScreen(ui: ReactElement) {
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
  mockApi.delete.mockReset();
  openURL.mockReset();
  openURL.mockResolvedValue(undefined);
  await i18n.changeLanguage('en');
});

const sessions = [
  {
    id: 's-old',
    platform: 'web',
    device_name: null,
    app_version: null,
    created_at: '2026-10-01T10:00:00Z',
    last_used_at: '2026-10-02T10:00:00Z',
    is_current: false,
  },
  {
    id: 's-me',
    platform: 'android',
    device_name: 'Pixel 9',
    app_version: '0.1.0',
    created_at: '2026-11-01T10:00:00Z',
    last_used_at: '2026-11-10T09:00:00Z',
    is_current: true,
  },
];

describe('devices', () => {
  it('lists this device first and signs another one out after confirming', async () => {
    mockApi.get.mockResolvedValue({ data: sessions });
    mockApi.delete.mockResolvedValue(undefined);
    const alert = jest.spyOn(Alert, 'alert').mockImplementation((_title, _body, buttons) => {
      buttons?.find((button) => button.style === 'destructive')?.onPress?.();
    });
    await renderScreen(<Sessions />);

    expect(await screen.findByTestId('session-s-me')).toHaveTextContent(
      'Pixel 9This device · version 0.1.0',
    );
    expect(screen.getByTestId('session-s-old')).toHaveTextContent(/Web browser/);
    expect(screen.queryByTestId('session-signout-s-me')).toBeNull(); // not the current device

    await fireEvent.press(screen.getByTestId('session-signout-s-old'));
    expect(alert).toHaveBeenCalledWith(
      'Sign out this device?',
      'Web browser will need to sign in again.',
      expect.any(Array),
    );
    await waitFor(() => expect(mockApi.delete).toHaveBeenCalledWith('/v1/users/me/sessions/s-old'));
    alert.mockRestore();
  });

  it('explains a loading failure', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('offline'));
    await renderScreen(<Sessions />);
    expect(await screen.findByTestId('sessions-error')).toBeTruthy();
  });
});

function entitlements(overrides: Partial<Entitlements> = {}): Entitlements {
  const quota = (used: number, limit: number) => ({ used, limit, resets_at: null });
  return {
    plan: 'premium',
    status: 'active',
    premium_until: '2026-12-10T10:00:00Z',
    store_grace_until: null,
    features: {},
    quotas: {
      'ai.itinerary_generations': quota(2, 60),
      'ai.trip_replans': quota(0, 60),
      'offline.packages': quota(1, 15),
      'groups.owned': quota(0, 10),
    },
    active_subscription: {
      provider: 'google',
      product_id: 'p1',
      auto_renew: true,
      management: 'google_play',
    },
    ...overrides,
  };
}

describe('subscription', () => {
  it('shows the renewal and opens the store page to manage it', async () => {
    mockApi.get.mockResolvedValueOnce(entitlements());
    await renderScreen(<Subscription />);
    expect(await screen.findByTestId('subscription-plan')).toHaveTextContent('Premium');
    expect(screen.getByTestId('subscription-summary')).toHaveTextContent(/^Renews on /);
    expect(screen.getByTestId('quota-ai.itinerary_generations')).toHaveTextContent(
      'AI trip plans2 of 60',
    );
    await fireEvent.press(screen.getByTestId('subscription-manage'));
    expect(openURL).toHaveBeenCalledWith(
      'https://play.google.com/store/account/subscriptions?package=com.travelbuddy.app',
    );
    expect(mockApi.get).toHaveBeenCalledWith('/v1/billing/entitlements');
  });

  it('warns about a failed payment during the store grace period', async () => {
    mockApi.get.mockResolvedValueOnce(
      entitlements({
        status: 'in_grace_period',
        store_grace_until: '2026-11-20T10:00:00Z',
        active_subscription: {
          provider: 'apple',
          product_id: 'p1',
          auto_renew: true,
          management: 'app_store',
        },
      }),
    );
    await renderScreen(<Subscription />);
    expect(await screen.findByTestId('subscription-billing-issue')).toHaveTextContent(
      /Update your payment method in your store account before /,
    );
    await fireEvent.press(screen.getByTestId('subscription-manage'));
    expect(openURL).toHaveBeenCalledWith('https://apps.apple.com/account/subscriptions');
  });

  it('shows the free plan and which features need Premium', async () => {
    mockApi.get.mockResolvedValueOnce(
      entitlements({
        plan: 'free',
        status: 'expired',
        premium_until: null,
        active_subscription: null,
        quotas: {
          'ai.itinerary_generations': { used: 1, limit: 5, resets_at: null },
          'ai.trip_replans': { used: 0, limit: 0, resets_at: null },
          'offline.packages': { used: 0, limit: 1, resets_at: null },
          'groups.owned': { used: 0, limit: 0, resets_at: null },
        },
      }),
    );
    await renderScreen(<Subscription />);
    expect(await screen.findByTestId('subscription-plan')).toHaveTextContent('Free plan');
    expect(screen.getByTestId('subscription-ended')).toHaveTextContent(
      'Your Premium subscription has ended.',
    );
    expect(screen.getByTestId('quota-groups.owned')).toHaveTextContent(
      'Groups you ownPremium only',
    );
    expect(screen.queryByTestId('subscription-manage')).toBeNull();
  });

  it('labels promotional Premium and web subscriptions', async () => {
    mockApi.get.mockResolvedValueOnce(entitlements({ active_subscription: null }));
    await renderScreen(<Subscription />);
    expect(await screen.findByTestId('subscription-summary')).toHaveTextContent(
      /^Premium from a promotion until /,
    );
  });

  it('points web subscribers to the website', async () => {
    mockApi.get.mockResolvedValueOnce(
      entitlements({
        active_subscription: {
          provider: 'stripe',
          product_id: 'p1',
          auto_renew: false,
          management: 'stripe_portal',
        },
      }),
    );
    await renderScreen(<Subscription />);
    expect(await screen.findByTestId('subscription-web')).toBeTruthy();
    expect(screen.getByTestId('subscription-summary')).toHaveTextContent(/won't renew/);
    expect(screen.queryByTestId('subscription-manage')).toBeNull();
  });
});

describe('follow requests', () => {
  it('approves and declines requests to a private account', async () => {
    mockApi.post.mockReset();
    mockApi.get.mockResolvedValue({
      data: [
        { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null },
        { id: 'u3', handle: 'cy', display_name: 'Cy', avatar: null },
      ],
      page: { next_cursor: null, has_more: false },
    });
    mockApi.post.mockResolvedValue(undefined);
    await renderScreen(<FollowRequests />);
    await fireEvent.press(await screen.findByTestId('follow-approve-u2'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/follow-requests/u2/approve'),
    );
    await fireEvent.press(screen.getByTestId('follow-decline-u3'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/follow-requests/u3/decline'),
    );
    expect(mockApi.get).toHaveBeenCalledWith('/v1/users/me/follow-requests', {
      query: { limit: 50 },
    });
  });

  it('says when nobody is waiting', async () => {
    mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } });
    await renderScreen(<FollowRequests />);
    expect(await screen.findByTestId('follow-requests-empty')).toBeTruthy();
  });
});
