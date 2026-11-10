// req: AUTH-011
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Linking } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { i18n } from '@/i18n';

import YourData from '../app/settings/data';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null } }));

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

const ready = {
  id: 'x1',
  kind: 'export',
  status: 'completed',
  requested_at: '2026-11-01T10:00:00Z',
  completed_at: '2026-11-01T10:05:00Z',
  download: { url: 'https://api.example/v1/data-exports/tok', expires_at: '2026-11-08T10:05:00Z' },
};

beforeEach(async () => {
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  await i18n.changeLanguage('en');
});

it('requests an export with an idempotency key and offers the download link', async () => {
  const openURL = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
  mockApi.get.mockResolvedValue({ data: [ready], page: { next_cursor: null } });
  mockApi.post.mockResolvedValueOnce({ ...ready, id: 'x2', status: 'received', download: null });
  await renderUi(<YourData />);
  await fireEvent.press(await screen.findByTestId('data-download-x1'));
  expect(openURL).toHaveBeenCalledWith('https://api.example/v1/data-exports/tok');
  await fireEvent.press(screen.getByTestId('data-request'));
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/data-exports', {
      idempotencyKey: 'key-1',
    }),
  );
});

it('says when an export is already on its way', async () => {
  mockApi.get.mockResolvedValue({
    data: [{ ...ready, status: 'processing', download: null }],
    page: { next_cursor: null },
  });
  await renderUi(<YourData />);
  expect(await screen.findByTestId('data-preparing')).toBeTruthy();
  expect(screen.queryByTestId('data-request')).toBeNull();
});

it('explains a refused request', async () => {
  mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null } });
  mockApi.post.mockRejectedValueOnce(
    new ApiProblem({ type: 'x', title: 'Conflict', status: 409, code: 'conflict' }, 'r'),
  );
  await renderUi(<YourData />);
  await fireEvent.press(await screen.findByTestId('data-request'));
  expect(await screen.findByText('Your data is already being prepared.')).toBeTruthy();
});
