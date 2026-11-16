// req: PROV-006, PROV-007, PROV-008, PROV-009, PROV-010, PROV-011, PROV-003
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import {
  actionsFor,
  type Inquiry,
  type Offering,
  type ProviderProfile,
  type ProviderWorkspace,
} from '@/features/providers/api';
import { formatPrice, parseAmount } from '@/features/providers/format';
import { LocalProviders } from '@/features/providers/LocalProviders';
import { notificationRoute } from '@/features/push/push';
import { i18n } from '@/i18n';

import RequestDetail from '../app/provider-requests/[id]';
import Provider from '../app/providers/[id]';
import Providers from '../app/providers/index';
import RequestForm from '../app/providers/request';
import Workspace from '../app/providers/workspace/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Stack: { Screen: () => null },
}));

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

const rio = {
  id: 'd-rio',
  kind: 'city',
  slug: 'rio-de-janeiro',
  path: 'brazil/rio-de-janeiro',
  name: 'Rio de Janeiro',
  country_code: 'BR',
  country_name: 'Brazil',
};
const page = <T,>(data: T[]) => ({ data, page: { next_cursor: null, has_more: false } });

function provider(overrides: Partial<ProviderProfile> = {}): ProviderProfile {
  return {
    id: 'p1',
    slug: 'carioca-walks-abc123',
    kind: 'guide',
    status: 'approved',
    display_name: 'Carioca Walks',
    tagline: 'Hidden Rio on foot',
    logo: null,
    cover: null,
    base_destination: rio,
    languages: ['pt-BR', 'en'],
    specialties: ['city_tours'],
    rating_average: 4.8,
    rating_count: 12,
    verified_at: '2026-11-16T10:00:00Z',
    response_time_seconds: 5400,
    about: 'Born in Santa Teresa.',
    years_experience: 8,
    website_url: null,
    service_areas: [],
    published_offering_count: 1,
    membership: null,
    ...overrides,
  };
}

const offering: Offering = {
  id: 'o1',
  provider: provider(),
  status: 'published',
  kind: 'tour',
  title: 'Santa Teresa at sunset',
  description: null,
  destination: rio,
  duration_minutes: 180,
  price_from: { amount_minor: 15000, currency: 'BRL', unit: 'per_person' },
  max_group_size: 8,
  languages: ['en'],
  cover: null,
  published_at: '2026-11-16T10:00:00Z',
  version: 1,
};

function inquiry(overrides: Partial<Inquiry> = {}): Inquiry {
  return {
    id: 'r1',
    provider: provider(),
    traveler: { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null },
    offering: { id: 'o1', title: 'Santa Teresa at sunset', kind: 'tour' },
    start_date: '2026-12-01',
    end_date: null,
    flexible_dates: false,
    party_size: 2,
    message: 'Could you show us Santa Teresa?',
    status: 'open',
    decline_reason: null,
    conversation_id: 'c-prov',
    first_response_at: null,
    viewer_side: 'traveler',
    can_review: false,
    review_id: null,
    created_at: '2026-11-16T10:00:00Z',
    version: 1,
    ...overrides,
  };
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  mockParams = {};
  await i18n.changeLanguage('en');
});

describe('helpers', () => {
  it('maps request states to what each side may do', () => {
    expect(actionsFor({ status: 'open', viewer_side: 'provider' })).toEqual(['accept', 'decline']);
    expect(actionsFor({ status: 'open', viewer_side: 'traveler' })).toEqual(['withdraw']);
    expect(actionsFor({ status: 'accepted', viewer_side: 'provider' })).toEqual([
      'complete',
      'cancel',
    ]);
    expect(actionsFor({ status: 'completed', viewer_side: 'traveler' })).toEqual([]);
  });

  it('parses typed amounts and formats indicative prices', () => {
    expect(parseAmount('150')).toBe(15000);
    expect(parseAmount('150,5')).toBe(15050);
    expect(parseAmount('1.234,50')).toBe(123450);
    expect(parseAmount('abc')).toBeNull();
    expect(formatPrice({ amount_minor: 15000, currency: 'BRL', unit: null }, 'en')).toContain(
      '150',
    );
  });

  it('routes provider notifications', () => {
    expect(notificationRoute('provider_inquiry', 'r1')).toEqual({
      pathname: '/provider-requests/[id]',
      params: { id: 'r1' },
    });
    expect(notificationRoute('provider', 'p1')).toEqual({ pathname: '/providers/mine' });
  });
});

describe('browsing', () => {
  it('lists providers for a destination and filters by kind', async () => {
    mockParams = { destinationId: 'd-rio', place: 'Rio de Janeiro' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/providers' ? page([provider()]) : {},
    );
    await renderUi(<Providers />);
    expect(await screen.findByTestId('provider-p1')).toHaveTextContent(/Carioca Walks/);
    expect(mockApi.get).toHaveBeenCalledWith('/v1/providers', {
      query: { destination_id: 'd-rio', kind: undefined, limit: 50 },
    });
    await fireEvent.press(screen.getByTestId('providers-kind-company'));
    await waitFor(() =>
      expect(mockApi.get).toHaveBeenCalledWith('/v1/providers', {
        query: { destination_id: 'd-rio', kind: 'company', limit: 50 },
      }),
    );
    await fireEvent.press(screen.getByTestId('provider-p1'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/providers/[id]',
      params: { id: 'p1' },
    });
  });

  it('shows the destination section only when someone serves it', async () => {
    mockApi.get.mockResolvedValueOnce(page([]));
    await renderUi(<LocalProviders destination={rio} />);
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(screen.queryByTestId('local-providers')).toBeNull();
  });

  it('lists local providers with a link to all of them', async () => {
    mockApi.get.mockResolvedValueOnce(page([provider()]));
    await renderUi(<LocalProviders destination={rio} />);
    expect(await screen.findByTestId('local-providers')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('local-providers-all'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/providers',
      params: { destinationId: 'd-rio', place: 'Rio de Janeiro' },
    });
  });

  it('shows a verified profile with offerings, price and reviews', async () => {
    useSessionStore.setState({ status: 'signed_in' });
    mockParams = { id: 'p1' };
    mockApi.get.mockImplementation(async (path: string) => {
      if (path === '/v1/providers/p1') return provider();
      if (path === '/v1/providers/p1/offerings') return page([offering]);
      if (path === '/v1/providers/p1/reviews') {
        return page([
          {
            id: 'rv1',
            provider_id: 'p1',
            rating: 5,
            body: 'Wonderful',
            author: null,
            reply: { body: 'Obrigada!', replied_at: '2026-11-16T10:00:00Z' },
            created_at: '2026-11-16T10:00:00Z',
          },
        ]);
      }
      return {};
    });
    await renderUi(<Provider />);
    expect(await screen.findByTestId('provider-verified')).toBeTruthy();
    expect(await screen.findByTestId('offering-o1')).toHaveTextContent(/150/);
    expect(await screen.findByTestId('review-rv1')).toHaveTextContent(/Former traveler/);
    await fireEvent.press(screen.getByTestId('provider-request'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/providers/request',
      params: { providerId: 'p1' },
    });
  });
});

describe('requests', () => {
  it('sends a request with safety tips and opens it', async () => {
    mockParams = { providerId: 'p1', offeringId: 'o1' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/providers/p1' ? provider() : {},
    );
    mockApi.post.mockResolvedValue(inquiry());
    await renderUi(<RequestForm />);
    expect(await screen.findByTestId('provider-safety-tips')).toBeTruthy();
    expect(screen.getByTestId('request-submit')).toBeDisabled();
    await fireEvent.changeText(screen.getByTestId('request-start'), '2099-01-10');
    await fireEvent.changeText(screen.getByTestId('request-message'), 'Two of us, sunset please!');
    await fireEvent.press(screen.getByTestId('request-submit'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/providers/p1/inquiries', {
        idempotencyKey: 'key-1',
        body: {
          offering_id: 'o1',
          flexible_dates: false,
          start_date: '2099-01-10',
          end_date: null,
          party_size: 2,
          message: 'Two of us, sunset please!',
        },
      }),
    );
    expect(mockRouter.replace).toHaveBeenCalledWith({
      pathname: '/provider-requests/[id]',
      params: { id: 'r1' },
    });
  });

  it('explains an already open request', async () => {
    mockParams = { providerId: 'p1' };
    mockApi.get.mockImplementation(async () => ({}));
    mockApi.post.mockRejectedValue(
      new ApiProblem(
        {
          type: 'https://errors.travelbuddy.app/inquiry_already_open',
          title: 'Conflict',
          status: 409,
          code: 'inquiry_already_open',
        },
        'req-1',
      ),
    );
    await renderUi(<RequestForm />);
    await fireEvent.press(screen.getByTestId('request-flexible'));
    await fireEvent.changeText(screen.getByTestId('request-message'), 'Any day next week works.');
    await fireEvent.press(screen.getByTestId('request-submit'));
    expect(await screen.findByTestId('request-error')).toHaveTextContent(/already have an open/);
  });

  it('lets the provider accept an open request', async () => {
    mockParams = { id: 'r1' };
    mockApi.get.mockResolvedValue(inquiry({ viewer_side: 'provider' }));
    mockApi.post.mockResolvedValue(inquiry({ viewer_side: 'provider', status: 'accepted' }));
    await renderUi(<RequestDetail />);
    expect(await screen.findByTestId('request-accept')).toBeTruthy();
    expect(screen.getByTestId('request-decline')).toBeTruthy();
    await fireEvent.press(screen.getByTestId('request-accept'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/provider-inquiries/r1/accept', {
        body: undefined,
      }),
    );
    expect(await screen.findByTestId('request-complete')).toBeTruthy();
  });

  it('asks the traveler for a review after a completed request', async () => {
    mockParams = { id: 'r1' };
    mockApi.get.mockResolvedValue(inquiry({ status: 'completed', can_review: true }));
    mockApi.post.mockResolvedValue({ id: 'rv1' });
    await renderUi(<RequestDetail />);
    expect(await screen.findByTestId('request-review')).toBeTruthy();
    expect(screen.getByTestId('review-submit')).toBeDisabled();
    await fireEvent.press(screen.getByTestId('review-star-4'));
    await fireEvent.changeText(screen.getByTestId('review-body'), 'Lovely afternoon');
    await fireEvent.press(screen.getByTestId('review-submit'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/provider-inquiries/r1/review', {
        body: { rating: 4, body: 'Lovely afternoon' },
      }),
    );
  });
});

describe('workspace', () => {
  function workspace(overrides: Partial<ProviderWorkspace> = {}): ProviderWorkspace {
    return {
      ...provider({
        status: 'draft',
        verified_at: null,
        membership: { role: 'owner', status: 'active' },
      }),
      country_code: 'BR',
      legal_name: 'Ana Souza',
      registration_number: null,
      review_note: null,
      suspended_reason: null,
      submitted_at: null,
      decided_at: null,
      locked_fields: [],
      terms_version: '2026-11-16',
      terms_accepted_version: null,
      missing_for_submit: ['document:identity'],
      inquiry_count: 0,
      response_count: 0,
      version: 1,
      created_at: '2026-11-16T10:00:00Z',
      ...overrides,
    };
  }

  it('lists what is missing and keeps submit off until it is complete', async () => {
    mockParams = { id: 'p1' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/providers/p1/workspace' ? workspace() : { data: [] },
    );
    await renderUi(<Workspace />);
    expect(await screen.findByTestId('workspace-checklist')).toHaveTextContent(/ID document/);
    await fireEvent(screen.getByTestId('workspace-terms'), 'valueChange', true);
    expect(screen.getByTestId('workspace-submit')).toBeDisabled();
  });

  it('submits a complete application with the current terms version', async () => {
    mockParams = { id: 'p1' };
    mockApi.get.mockImplementation(async (path: string) =>
      path === '/v1/providers/p1/workspace' ? workspace({ missing_for_submit: [] }) : { data: [] },
    );
    mockApi.post.mockResolvedValue(workspace({ status: 'submitted', missing_for_submit: [] }));
    await renderUi(<Workspace />);
    await fireEvent(await screen.findByTestId('workspace-terms'), 'valueChange', true);
    await fireEvent.press(screen.getByTestId('workspace-submit'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/providers/p1/submit', {
        body: { terms_version: '2026-11-16' },
      }),
    );
    expect(await screen.findByTestId('workspace-status')).toHaveTextContent('In review');
  });
});
