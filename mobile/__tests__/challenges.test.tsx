// req: CHAL-004, CHAL-005, CHAL-008, CHAL-011, CHAL-015
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { badgeKey, type Challenge } from '@/features/challenges/api';
import { i18n } from '@/i18n';

import ChallengeScreen from '../app/challenges/[id]';
import ChallengesScreen from '../app/challenges/index';
import NewChallenge from '../app/challenges/new';
import Fulfillments from '../app/challenges/fulfillments';
import Review from '../app/challenges/review';
import Rewards from '../app/rewards';

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

function problem(code: string, status = 409) {
  return new ApiProblem({ type: 'x', title: 'Problem', status, code }, 'r');
}

const person = (id: string, name: string) => ({
  id,
  handle: name.toLowerCase(),
  display_name: name,
  avatar: null,
});

function group(permissions: string[]) {
  return {
    id: 'g1',
    name: 'Lisbon crew',
    description: null,
    cover: null,
    primary_destination: { id: 'd1', name: 'Lisbon' },
    start_date: null,
    end_date: null,
    member_capacity: 10,
    member_count: 4,
    owner: person('u1', 'Owner'),
    status: 'active',
    conversation_id: 'conv-group',
    premium_features_active: true,
    my_membership: { role: 'member', status: 'active', permissions, restricted_until: null },
    version: 1,
  };
}

function challenge(overrides: Partial<Challenge> = {}): Challenge {
  return {
    id: 'c1',
    group_id: 'g1',
    kind: 'riddle',
    title: 'Where is the tower?',
    description: 'I guard the river mouth and saw the caravels leave.',
    media: null,
    solving_mode: 'individual',
    validation_method: 'exact',
    max_attempts: 3,
    attempt_cooldown_seconds: 30,
    winner_policy: 'first_correct',
    max_winners: 1,
    prize_description: 'Bragging rights',
    rewards: [
      {
        id: 'r1',
        reward_type: 'badge',
        title: 'Explorer',
        description: null,
        sponsor_name: null,
        quantity: 1,
        terms_url: null,
      },
    ],
    participation_rules: null,
    starts_at: '2026-11-10T10:00:00Z',
    ends_at: '2026-11-11T10:00:00Z',
    status: 'active',
    published_at: '2026-11-10T09:00:00Z',
    results_published_at: null,
    rules_version: 1,
    hints: [
      { id: 'h1', sort_order: 0, body: 'Think Manueline.', released_at: '2026-11-10T10:00:00Z' },
    ],
    my_participation: null,
    ...overrides,
  };
}

function serve(routes: Record<string, unknown>) {
  mockApi.get.mockImplementation((path: string) =>
    path in routes ? Promise.resolve(routes[path]) : Promise.reject(problem('not_found', 404)),
  );
}

beforeEach(async () => {
  for (const fn of [
    mockApi.get,
    mockApi.post,
    mockApi.patch,
    mockRouter.push,
    mockRouter.replace,
  ]) {
    fn.mockReset();
  }
  mockParams = {};
  await i18n.changeLanguage('en');
});

it('makes badge keys from names', () => {
  expect(badgeKey('Old Town Explorer!')).toBe('old-town-explorer');
  expect(badgeKey('Ç')).toBe('c');
  expect(badgeKey('!!!')).toBe('challenge-badge');
});

describe('group challenges', () => {
  it('lists challenges and offers organizers a new one', async () => {
    mockParams = { groupId: 'g1' };
    serve({
      '/v1/groups/g1': group(['challenges.manage', 'challenges.judge']),
      '/v1/groups/g1/challenges': { data: [challenge()], page: { next_cursor: null } },
    });
    await renderUi(<ChallengesScreen />);
    await fireEvent.press(await screen.findByTestId('challenge-c1'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/challenges/[id]',
      params: { id: 'c1' },
    });
    await fireEvent.press(screen.getByTestId('challenges-new'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/challenges/new',
      params: { groupId: 'g1' },
    });
  });

  it('shows members no organizer tools', async () => {
    mockParams = { groupId: 'g1' };
    serve({
      '/v1/groups/g1': group([]),
      '/v1/groups/g1/challenges': { data: [], page: { next_cursor: null } },
    });
    await renderUi(<ChallengesScreen />);
    expect(await screen.findByText('No challenges in this group yet.')).toBeTruthy();
    expect(screen.queryByTestId('challenges-new')).toBeNull();
  });
});

describe('solving a challenge', () => {
  beforeEach(() => {
    mockParams = { id: 'c1' };
  });

  it('sends answers with an idempotency key and reports only the verdict', async () => {
    serve({ '/v1/challenges/c1': challenge(), '/v1/groups/g1': group([]) });
    mockApi.post.mockResolvedValueOnce({
      submission_id: 's1',
      attempt_no: 1,
      evaluation_status: 'incorrect',
      attempts_remaining: 2,
      next_attempt_at: '2026-11-10T10:00:30Z',
      is_provisional_winner: false,
    });
    await renderUi(<ChallengeScreen />);
    expect(await screen.findByText('• Think Manueline.')).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('challenge-answer'), ' Jerónimos ');
    await fireEvent.press(screen.getByTestId('challenge-submit'));
    expect(await screen.findByText('Not quite. 2 attempts left.')).toBeTruthy();
    expect(mockApi.post).toHaveBeenCalledWith('/v1/challenges/c1/submissions', {
      idempotencyKey: 'key-1',
      body: { answer: 'Jerónimos' },
    });
  });

  it('explains cooldowns and celebrates a provisional win', async () => {
    serve({ '/v1/challenges/c1': challenge(), '/v1/groups/g1': group([]) });
    mockApi.post.mockRejectedValueOnce(problem('attempt_cooldown')).mockResolvedValueOnce({
      submission_id: 's2',
      attempt_no: 2,
      evaluation_status: 'correct',
      attempts_remaining: 1,
      next_attempt_at: null,
      is_provisional_winner: true,
    });
    await renderUi(<ChallengeScreen />);
    await fireEvent.changeText(await screen.findByTestId('challenge-answer'), 'Belém Tower');
    await fireEvent.press(screen.getByTestId('challenge-submit'));
    expect(await screen.findByText('Wait a moment before trying again.')).toBeTruthy();
    await fireEvent.changeText(screen.getByTestId('challenge-answer'), 'Belém Tower');
    await fireEvent.press(screen.getByTestId('challenge-submit'));
    expect(await screen.findByTestId('challenge-outcome')).toHaveTextContent(
      "Correct! You're in the lead. It becomes final when the results are published.",
    );
    expect(screen.queryByTestId('challenge-answer')).toBeNull(); // solved: no more answers
  });

  it('lets people join a team; only the captain answers', async () => {
    const teams = {
      data: [
        {
          id: 't1',
          challenge_id: 'c1',
          name: 'Navigators',
          captain: person('u2', 'Ana'),
          members: [person('u2', 'Ana')],
          conversation_id: 'conv-team',
          created_at: '2026-11-10T09:30:00Z',
        },
      ],
      page: { next_cursor: null },
    };
    serve({
      '/v1/challenges/c1': challenge({ solving_mode: 'team' }),
      '/v1/groups/g1': group([]),
      '/v1/challenges/c1/teams': teams,
    });
    mockApi.post.mockResolvedValueOnce(teams.data[0]);
    await renderUi(<ChallengeScreen />);
    expect(await screen.findByText('Navigators · 1 member')).toBeTruthy();
    expect(screen.queryByTestId('challenge-answer')).toBeNull(); // no team yet
    await fireEvent.press(screen.getByTestId('challenge-join-t1'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/challenges/c1/teams/t1/join'),
    );
  });

  it('sends teammates to the team chat instead of the answer box', async () => {
    serve({
      '/v1/challenges/c1': challenge({
        solving_mode: 'team',
        my_participation: {
          attempts_used: 1,
          attempts_remaining: 2,
          next_attempt_at: null,
          team_id: 't1',
          is_captain: false,
          status: 'active',
        },
      }),
      '/v1/groups/g1': group([]),
      '/v1/challenges/c1/teams': {
        data: [
          {
            id: 't1',
            challenge_id: 'c1',
            name: 'Navigators',
            captain: person('u2', 'Ana'),
            members: [person('u2', 'Ana'), person('u9', 'Me')],
            conversation_id: 'conv-team',
            created_at: '2026-11-10T09:30:00Z',
          },
        ],
        page: { next_cursor: null },
      },
    });
    await renderUi(<ChallengeScreen />);
    expect(await screen.findByTestId('challenge-captain-only')).toBeTruthy();
    expect(screen.getByTestId('challenge-attempts')).toHaveTextContent('2 attempts left');
    expect(screen.queryByTestId('challenge-answer')).toBeNull();
    await fireEvent.press(screen.getByTestId('challenge-team-chat'));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: '/chat/[id]',
      params: { id: 'conv-team' },
    });
  });

  it('shows published winners', async () => {
    serve({
      '/v1/challenges/c1': challenge({
        status: 'completed',
        results_published_at: '2026-11-11T11:00:00Z',
      }),
      '/v1/groups/g1': group([]),
      '/v1/challenges/c1/results': {
        challenge_id: 'c1',
        status: 'completed',
        published: true,
        results_published_at: '2026-11-11T11:00:00Z',
        participant_count: 3,
        winners: [
          {
            id: 'w1',
            rank: 1,
            user: person('u2', 'Ana'),
            team: null,
            status: 'confirmed',
            determined_by: 'system',
            determined_at: '2026-11-10T11:00:00Z',
          },
        ],
      },
    });
    await renderUi(<ChallengeScreen />);
    expect(await screen.findByText('#1 Ana')).toBeTruthy();
    expect(screen.queryByTestId('challenge-answer')).toBeNull();
  });
});

describe('creating a challenge', () => {
  it('saves a draft with normalized answers and a badge', async () => {
    mockParams = { groupId: 'g1' };
    mockApi.post.mockResolvedValueOnce({ id: 'c9' });
    await renderUi(<NewChallenge />);
    await fireEvent.changeText(screen.getByTestId('new-challenge-title'), 'Where is the tower?');
    await fireEvent.changeText(
      screen.getByTestId('new-challenge-riddle'),
      'I guard the river mouth and saw the caravels leave.',
    );
    await fireEvent.changeText(
      screen.getByTestId('new-challenge-answers'),
      'Belém Tower\n\n Torre de Belém ',
    );
    await fireEvent.press(screen.getByTestId('new-challenge-days-3'));
    await fireEvent.changeText(screen.getByTestId('new-challenge-badge'), 'River Explorer');
    await fireEvent.press(screen.getByTestId('new-challenge-save'));
    await waitFor(() =>
      expect(mockRouter.replace).toHaveBeenCalledWith({
        pathname: '/challenges/[id]',
        params: { id: 'c9' },
      }),
    );
    const [path, options] = mockApi.post.mock.calls[0];
    expect(path).toBe('/v1/groups/g1/challenges');
    expect(options.idempotencyKey).toBe('key-1');
    expect(options.body.accepted_answers).toEqual(['Belém Tower', 'Torre de Belém']);
    expect(options.body.rewards[0]).toMatchObject({
      reward_type: 'badge',
      badge_key: 'river-explorer',
    });
    const hours =
      (Date.parse(options.body.ends_at) - Date.parse(options.body.starts_at)) / 3_600_000;
    expect(hours).toBe(72);
  });

  it('explains refused prizes', async () => {
    mockParams = { groupId: 'g1' };
    mockApi.post.mockRejectedValueOnce(problem('reward_not_permitted', 422));
    await renderUi(<NewChallenge />);
    await fireEvent.changeText(screen.getByTestId('new-challenge-title'), 'Cash hunt');
    await fireEvent.changeText(
      screen.getByTestId('new-challenge-riddle'),
      'Find the hidden spot near the river.',
    );
    await fireEvent.changeText(screen.getByTestId('new-challenge-answers'), 'Belém');
    await fireEvent.press(screen.getByTestId('new-challenge-save'));
    expect(
      await screen.findByText("Prizes can't be cash, gift cards or raffles, or need paid entry."),
    ).toBeTruthy();
  });
});

it('shows reward codes to their recipient', async () => {
  serve({
    '/v1/users/me/rewards': {
      data: [
        {
          fulfillment_id: 'f1',
          challenge: { id: 'c1', title: 'Where is the tower?', group_id: 'g1' },
          reward: {
            id: 'r2',
            reward_type: 'discount_code',
            title: '10% off a tour',
            description: null,
            sponsor_name: 'Partner Tours',
            quantity: 1,
            terms_url: null,
          },
          status: 'issued',
          secret: 'TOUR10-BELEM',
          issued_at: '2026-11-11T12:00:00Z',
          delivered_at: null,
        },
      ],
      page: { next_cursor: null },
    },
  });
  await renderUi(<Rewards />);
  expect(await screen.findByTestId('reward-code-f1')).toHaveTextContent('TOUR10-BELEM');
  expect(screen.getByText('Where is the tower? · Ready')).toBeTruthy();
});

describe('judging', () => {
  it('lists waiting answers with the AI advice and records verdicts', async () => {
    mockParams = { id: 'c1' };
    const submission = {
      id: 's9',
      challenge_id: 'c1',
      submitted_by: person('u3', 'Caio'),
      team_id: null,
      attempt_no: 1,
      answer_text: 'The old fort by the river',
      evaluation_status: 'needs_review',
      evaluator: 'ai',
      ai_confidence: 0.55,
      ai_rationale: 'Probably the tower, but vague.',
      submitted_at: '2026-11-10T10:00:00Z',
      evaluated_at: null,
    };
    mockApi.get.mockImplementation((path: string, options?: { query?: Record<string, string> }) => {
      if (path === '/v1/challenges/c1/submissions') {
        return Promise.resolve({
          data: options?.query?.evaluation_status === 'needs_review' ? [submission] : [],
          page: { next_cursor: null },
        });
      }
      return Promise.resolve({
        challenge_id: 'c1',
        status: 'judging',
        published: false,
        results_published_at: null,
        participant_count: 2,
        winners: [
          {
            id: 'w1',
            rank: 1,
            user: person('u2', 'Ana'),
            team: null,
            status: 'provisional',
            determined_by: 'system',
            determined_at: '2026-11-10T10:00:00Z',
          },
        ],
      });
    });
    mockApi.post.mockResolvedValue({});
    await renderUi(<Review />);
    expect(await screen.findByTestId('review-ai-s9')).toHaveTextContent(
      'AI judge (55% sure): Probably the tower, but vague.',
    );
    await fireEvent.press(screen.getByTestId('review-correct-s9'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/challenges/c1/submissions/s9/judgement', {
        body: { evaluation_status: 'correct' },
      }),
    );
    await fireEvent.press(screen.getByTestId('review-confirm-w1'));
    await waitFor(() =>
      expect(mockApi.post).toHaveBeenCalledWith('/v1/challenges/c1/winners/w1/confirm'),
    );
  });

  it('lets participants dispute a finished challenge', async () => {
    mockParams = { id: 'c1' };
    serve({
      '/v1/challenges/c1': challenge({
        status: 'judging',
        my_participation: {
          attempts_used: 1,
          attempts_remaining: 2,
          next_attempt_at: null,
          team_id: null,
          is_captain: false,
          status: 'active',
        },
      }),
      '/v1/groups/g1': group([]),
    });
    mockApi.post.mockResolvedValueOnce({ id: 'd1' });
    await renderUi(<ChallengeScreen />);
    await fireEvent.changeText(
      await screen.findByTestId('challenge-dispute-reason'),
      'My answer was right but marked wrong.',
    );
    await fireEvent.press(screen.getByTestId('challenge-dispute-send'));
    expect(await screen.findByTestId('challenge-dispute-sent')).toBeTruthy();
    expect(mockApi.post).toHaveBeenCalledWith('/v1/challenges/c1/disputes', {
      body: { reason: 'My answer was right but marked wrong.' },
    });
  });
});

it('lets organizers issue a discount code and mark it delivered', async () => {
  mockParams = { id: 'c1' };
  const pending = {
    id: 'f1',
    challenge_reward_id: 'r2',
    winner_id: 'w1',
    recipient: person('u2', 'Ana'),
    status: 'pending',
    issued_at: null,
    delivered_at: null,
    notes: null,
    updated_at: '2026-11-11T12:00:00Z',
  };
  mockApi.get.mockResolvedValue({ data: [pending], page: { next_cursor: null } });
  mockApi.post.mockResolvedValue({ ...pending, status: 'issued' });
  await renderUi(<Fulfillments />);
  expect(screen.queryByTestId('fulfillment-delivered-f1')).toBeNull(); // not before issuing
  await fireEvent.changeText(await screen.findByTestId('fulfillment-code-f1'), ' tour10 ');
  await fireEvent.press(screen.getByTestId('fulfillment-issued-f1'));
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/challenges/c1/fulfillments/f1/transitions', {
      body: { to_status: 'issued', secret: 'tour10' },
    }),
  );
});

it('edits a draft with its version and keeps answers unless replaced', async () => {
  mockParams = { groupId: 'g1', edit: 'c1' };
  const starts = new Date(Date.now() + 60 * 60 * 1000);
  mockApi.get.mockResolvedValue({
    ...challenge({
      status: 'draft',
      starts_at: starts.toISOString(),
      ends_at: new Date(starts.getTime() + 3 * 86_400_000).toISOString(),
    }),
    answer_count: 2,
    participant_count: 0,
    pending_review_count: 0,
    version: 4,
  });
  mockApi.patch.mockResolvedValueOnce({ id: 'c1' });
  await renderUi(<NewChallenge />);
  expect(await screen.findByDisplayValue('Where is the tower?')).toBeTruthy();
  expect(screen.queryByTestId('new-challenge-badge')).toBeNull(); // set at creation only
  await fireEvent.changeText(screen.getByTestId('new-challenge-title'), 'Which tower?');
  await fireEvent.press(screen.getByTestId('new-challenge-save'));
  await waitFor(() => expect(mockApi.patch).toHaveBeenCalled());
  const [path, options] = mockApi.patch.mock.calls[0];
  expect(path).toBe('/v1/challenges/c1');
  expect(options.ifMatchVersion).toBe(4);
  expect(options.body.title).toBe('Which tower?');
  expect(options.body.accepted_answers).toBeUndefined();
  const span = (Date.parse(options.body.ends_at) - Date.parse(options.body.starts_at)) / 86_400_000;
  expect(span).toBe(3);
  expect(mockRouter.replace).toHaveBeenCalledWith({
    pathname: '/challenges/[id]',
    params: { id: 'c1' },
  });
});
