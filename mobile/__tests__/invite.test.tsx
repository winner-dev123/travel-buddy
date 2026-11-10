// req: GRP-005
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { takeHomeRoute, useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { i18n } from '@/i18n';

import Invite from '../app/invite';

const mockApi = { get: jest.fn(), post: jest.fn(), newIdempotencyKey: jest.fn(() => 'k1') };
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockUrl: string | null = null;
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Stack: { Screen: () => null },
}));
jest.mock('expo-linking', () => ({ useLinkingURL: () => mockUrl }));

const TOKEN = 'Abc_123-'.repeat(5);
const preview = {
  group: {
    id: 'g1',
    name: 'Lisbon food crawl',
    cover: null,
    primary_destination: { id: 'd1', name: 'Lisbon', path: 'portugal/lisbon' },
    member_count: 4,
  },
  inviter: { id: 'u1', handle: 'ana', display_name: 'Ana', avatar: null },
  expires_at: '2026-11-17T10:00:00Z',
  is_member: false,
};

async function renderInvite() {
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
        <Invite />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

const me = {
  account: { id: 'u9', email: 'me@example.com', email_verified: true, status: 'active' },
  onboarding_completed: true,
} as unknown as Me;

beforeEach(async () => {
  jest.clearAllMocks();
  mockParams = {};
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

it('previews the group from the link and joins it', async () => {
  mockUrl = `travelbuddy://invite#t=${TOKEN}`;
  mockApi.post.mockImplementation(async (path: string) =>
    path === '/v1/group-invitations/preview' ? preview : { group_id: 'g1' },
  );
  await renderInvite();
  expect(await screen.findByTestId('invite-preview')).toHaveTextContent(/Lisbon food crawl/);
  expect(screen.getByText('Invited by Ana')).toBeTruthy();
  expect(mockApi.post).toHaveBeenCalledWith('/v1/group-invitations/preview', {
    body: { token: TOKEN },
  });

  await fireEvent.press(screen.getByTestId('invite-join'));
  await waitFor(() =>
    expect(mockRouter.replace).toHaveBeenCalledWith({
      pathname: '/groups/[id]',
      params: { id: 'g1' },
    }),
  );
  expect(mockApi.post).toHaveBeenCalledWith('/v1/group-invitations/redeem', {
    body: { token: TOKEN },
  });
});

it('refuses a link without a token and never calls the API', async () => {
  mockUrl = 'travelbuddy://invite';
  await renderInvite();
  expect(screen.getByTestId('invite-invalid')).toHaveTextContent(
    "This invitation isn't valid. Ask for a new link.",
  );
  expect(mockApi.post).not.toHaveBeenCalled();
});

it('explains a full group', async () => {
  mockUrl = `travelbuddy://invite#t=${TOKEN}`;
  mockApi.post.mockRejectedValue(
    new ApiProblem({ type: 'x', title: 'Full', status: 409, code: 'group_capacity_reached' }, 'r'),
  );
  await renderInvite();
  expect(await screen.findByTestId('invite-invalid')).toHaveTextContent('This group is full.');
});

it('asks a signed-out traveller to sign in and brings them back afterwards', async () => {
  useSessionStore.getState().setSignedOut();
  mockUrl = `travelbuddy://invite#t=${TOKEN}`;
  await renderInvite();
  expect(screen.getByTestId('invite-sign-in-note')).toHaveTextContent(
    'Sign in to see this group and join it.',
  );
  expect(screen.queryByTestId('invite-invalid')).toBeNull();
  expect(mockApi.post).not.toHaveBeenCalled(); // the preview needs an account

  await fireEvent.press(screen.getByTestId('invite-sign-in'));
  expect(mockRouter.push).toHaveBeenCalledWith('/sign-in');
  useSessionStore.getState().setSignedIn(me);
  expect(takeHomeRoute()).toEqual({ pathname: '/invite', params: { t: TOKEN } });
  expect(takeHomeRoute()).toBe('/'); // used once
});

it('reads the token from the route params: a query or the fragment', async () => {
  mockUrl = 'travelbuddy://invite';
  mockApi.post.mockResolvedValue(preview);
  mockParams = { '#': `t=${TOKEN}` }; // Expo Router's form of `#t=<token>`
  await renderInvite();
  expect(await screen.findByTestId('invite-preview')).toBeTruthy();
  expect(mockApi.post).toHaveBeenCalledWith('/v1/group-invitations/preview', {
    body: { token: TOKEN },
  });
});
