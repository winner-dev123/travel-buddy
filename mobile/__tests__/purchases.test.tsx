// req: BILL-004, BILL-011
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { i18n } from '@/i18n';

import Purchases, { formatAmount } from '../app/settings/purchases';

const mockApi = { get: jest.fn() };

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null } }));

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

const pass = { id: 'p1', kind: 'non_renewing', period: 'P1M', title: 'Month pass' };
const row = (overrides: Record<string, unknown>) => ({
  id: 't1',
  provider: 'stripe',
  kind: 'payment',
  status: 'succeeded',
  amount_minor: 1490,
  currency: 'BRL',
  reason: 'purchase',
  receipt_url: null,
  product: pass,
  occurred_at: '2026-11-11T10:00:00Z',
  ...overrides,
});
const page = (data: unknown[], next: string | null = null) => ({
  data,
  page: { next_cursor: next, has_more: next !== null },
});

beforeEach(async () => {
  jest.clearAllMocks();
  mockApi.get.mockReset();
  await i18n.changeLanguage('en');
});

describe('purchase history', () => {
  it('lists payments, refunds and chargebacks with their status', async () => {
    mockApi.get.mockResolvedValueOnce(
      page([
        row({ id: 't1', receipt_url: 'https://invoice.stripe.com/i/in_1' }),
        row({ id: 't2', kind: 'refund', amount_minor: 1490, product: null }),
        row({ id: 't3', kind: 'dispute', status: 'lost', product: null }),
        row({ id: 't4', provider: 'apple', amount_minor: null, currency: null }),
        row({ id: 't5', status: 'failed' }),
      ]),
    );
    await renderScreen(<Purchases />);
    expect(await screen.findByTestId('purchase-t1')).toBeTruthy();
    expect(mockApi.get).toHaveBeenCalledWith('/v1/billing/transactions', { query: {} });
    expect(screen.getByTestId('purchase-status-t1')).toHaveTextContent('Paid');
    expect(screen.getByTestId('purchase-t1')).toHaveTextContent(/Month pass.*R\$14\.90/);
    expect(screen.getByTestId('purchase-t2')).toHaveTextContent(/Refund.*−R\$14\.90/);
    expect(screen.getByTestId('purchase-status-t2')).toHaveTextContent('Refunded');
    expect(screen.getByTestId('purchase-status-t3')).toHaveTextContent('Chargeback refunded');
    expect(screen.getByTestId('purchase-t4')).toHaveTextContent(/App Store/);
    expect(screen.getByTestId('purchase-t4')).toHaveTextContent(/Amount on your store receipt/);
    expect(screen.getByTestId('purchase-status-t5')).toHaveTextContent('Failed');
    expect(screen.getByLabelText(/^Month pass, R\$14\.90, Paid, /)).toBeTruthy();

    await fireEvent.press(screen.getByTestId('purchase-receipt-t1'));
    expect(openURL).toHaveBeenCalledWith('https://invoice.stripe.com/i/in_1');
    expect(screen.queryByTestId('purchase-receipt-t2')).toBeNull();
  });

  it('loads the next page at the end of the list', async () => {
    mockApi.get
      .mockResolvedValueOnce(page([row({ id: 't1' })], 'cursor-2'))
      .mockResolvedValueOnce(page([row({ id: 't9' })]));
    await renderScreen(<Purchases />);
    expect(await screen.findByTestId('purchase-t1')).toBeTruthy();
    await fireEvent(screen.getByTestId('purchases-list'), 'endReached');
    expect(await screen.findByTestId('purchase-t9')).toBeTruthy();
    expect(mockApi.get).toHaveBeenLastCalledWith('/v1/billing/transactions', {
      query: { cursor: 'cursor-2' },
    });
  });

  it('says when there is nothing yet', async () => {
    mockApi.get.mockResolvedValueOnce(page([]));
    await renderScreen(<Purchases />);
    expect(await screen.findByTestId('purchases-empty')).toHaveTextContent('No purchases yet.');
  });

  it('explains a failure to load', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('offline'));
    await renderScreen(<Purchases />);
    await waitFor(() => expect(screen.getByTestId('purchases-error')).toBeTruthy());
  });

  it('formats amounts in the currency of the payment', () => {
    expect(formatAmount(1490, 'BRL', 'pt-BR')).toMatch(/R\$\s?14,90/);
    expect(formatAmount(1490, 'JPY', 'en')).toBe('¥1,490');
    expect(formatAmount(990, 'EUR', 'de')).toMatch(/9,90\s?€/);
  });
});
