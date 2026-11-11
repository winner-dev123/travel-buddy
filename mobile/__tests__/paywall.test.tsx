// req: BILL-002, BILL-004, BILL-010
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { paywallReason } from '@/features/billing/purchases';
import { i18n } from '@/i18n';

import Paywall from '../app/paywall';

const mockApi = { get: jest.fn(), post: jest.fn(), newIdempotencyKey: jest.fn(() => 'key-1') };
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Stack: { Screen: () => null },
}));

const openURL = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);

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

const offer = (sku: string, kind: string, period: string | null, title: string) => ({
  id: `id-${sku}`,
  sku,
  platform: 'ios',
  provider: 'apple',
  kind,
  plan_key: kind === 'non_consumable' ? null : 'premium',
  period,
  entitlement_keys: ['premium'],
  title,
  description: `${title} description`,
});
const OFFERS = [
  offer('com.travelbuddy.premium.monthly', 'auto_renewable', 'P1M', 'Premium monthly'),
  offer('com.travelbuddy.pass.week', 'non_renewing', 'P7D', '7-day pass'),
  offer('com.travelbuddy.guide.lisbon', 'non_consumable', null, 'Lisbon guide'),
];
const quotas = {
  'ai.itinerary_generations': { limit: 5, used: 0, resets_at: null },
  'ai.trip_replans': { limit: 0, used: 0, resets_at: null },
  'offline.packages': { limit: 1, used: 0, resets_at: null },
  'groups.owned': { limit: 0, used: 0, resets_at: null },
};
const entitlements = (plan: 'free' | 'premium') => ({
  plan,
  status: plan === 'premium' ? 'active' : 'none',
  premium_until: null,
  store_grace_until: null,
  features: {},
  quotas,
  active_subscription: null,
});

function serve(plan: 'free' | 'premium') {
  mockApi.get.mockImplementation(async (path: string) => {
    if (path === '/v1/billing/products') return { data: OFFERS };
    if (path === '/v1/billing/entitlements') return entitlements(plan);
    if (path === '/v1/client-config') {
      return {
        legal: {
          terms_url: 'https://travelbuddy.example/terms',
          privacy_url: 'https://travelbuddy.example/privacy',
        },
      };
    }
    throw new Error(path);
  });
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  mockParams = {};
  delete process.env.EXPO_PUBLIC_PURCHASES;
  await i18n.changeLanguage('en');
});

describe('paywall', () => {
  it('shows why, the benefits and the Premium offers, without a way to buy yet', async () => {
    mockParams = { reason: 'groups.create' };
    serve('free');
    await renderScreen(<Paywall />);
    expect(await screen.findByTestId('paywall-offer-com.travelbuddy.pass.week')).toBeTruthy();
    expect(screen.getByTestId('paywall-reason')).toHaveTextContent(
      'Creating travel groups is part of Premium. Joining is always free.',
    );
    expect(screen.getByText('Up to 15 offline downloads')).toBeTruthy();
    expect(screen.queryByTestId('paywall-offer-com.travelbuddy.guide.lisbon')).toBeNull();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/billing/products', {
      query: { platform: 'ios' },
    });
    // Store rules: no web price and no link to buy elsewhere; buying waits for the store.
    expect(screen.getByTestId('paywall-buy')).toBeDisabled();
    expect(screen.getByTestId('paywall-soon')).toHaveTextContent(
      'Buying Premium in the app opens soon.',
    );
    expect(screen.getByTestId('paywall-disclosure')).toHaveTextContent(
      /App Store account settings/,
    );
    expect(screen.queryByText(/https?:\/\//)).toBeNull();
    await fireEvent.press(await screen.findByTestId('paywall-terms'));
    expect(openURL).toHaveBeenCalledWith('https://travelbuddy.example/terms');
    await fireEvent.press(screen.getByTestId('paywall-close'));
    expect(mockRouter.back).toHaveBeenCalled();
  });

  it('buys a pass through the test store in development builds', async () => {
    process.env.EXPO_PUBLIC_PURCHASES = 'test';
    serve('free');
    mockApi.post.mockResolvedValue({ entitlements: entitlements('premium') });
    await renderScreen(<Paywall />);
    await fireEvent.press(await screen.findByTestId('paywall-offer-com.travelbuddy.pass.week'));
    expect(screen.getByTestId('paywall-test-note')).toHaveTextContent(
      'Test purchase: nothing is charged.',
    );
    await fireEvent.press(screen.getByTestId('paywall-buy'));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    const [path, options] = mockApi.post.mock.calls[0];
    expect(path).toBe('/v1/billing/purchases/verify');
    expect(options.idempotencyKey).toBe('key-1');
    expect(options.body.provider).toBe('apple');
    expect(options.body.signed_transaction).toMatch(/^dev:com\.travelbuddy\.pass\.week:\w+$/);
    expect(await screen.findByTestId('paywall-success')).toHaveTextContent(
      'Premium is active. Enjoy your travels!',
    );
    await fireEvent.press(screen.getByTestId('paywall-done'));
    expect(mockRouter.back).toHaveBeenCalled();
  });

  it('says when a test purchase fails', async () => {
    process.env.EXPO_PUBLIC_PURCHASES = 'test';
    serve('free');
    mockApi.post.mockRejectedValue(new Error('refused'));
    await renderScreen(<Paywall />);
    await screen.findByTestId('paywall-offer-com.travelbuddy.premium.monthly');
    await fireEvent.press(screen.getByTestId('paywall-buy'));
    expect(await screen.findByTestId('paywall-failed')).toBeTruthy();
  });

  it('points Premium members to their subscription instead', async () => {
    mockParams = { reason: 'not-a-reason' };
    serve('premium');
    await renderScreen(<Paywall />);
    expect(await screen.findByTestId('paywall-already')).toBeTruthy();
    expect(screen.getByTestId('paywall-reason')).toHaveTextContent('Do more with every trip.');
    expect(screen.queryByTestId('paywall-buy')).toBeNull();
    await fireEvent.press(screen.getByTestId('paywall-manage'));
    expect(mockRouter.replace).toHaveBeenCalledWith('/settings/subscription');
  });

  it('only knows the documented reasons', () => {
    expect(paywallReason('guides.premium')).toBe('guides.premium');
    expect(paywallReason('anything')).toBeNull();
    expect(paywallReason(undefined)).toBeNull();
  });
});
