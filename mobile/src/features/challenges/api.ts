import type { ApiClient } from '@/api';
import type { MediaRef, Page, UserSummary } from '@/features/feed/types';

export type ChallengeStatus =
  'draft' | 'scheduled' | 'active' | 'judging' | 'completed' | 'cancelled';
export type SolvingMode = 'individual' | 'team';
export type ValidationMethod = 'exact' | 'admin_review' | 'ai_assisted';
export type WinnerPolicy = 'first_correct' | 'first_n_correct' | 'all_correct' | 'admin_selects';
export type EvaluationStatus = 'pending' | 'correct' | 'incorrect' | 'needs_review' | 'void';
export type RewardType = 'badge' | 'achievement' | 'discount_code' | 'promotional';
export type FulfillmentStatus =
  'pending' | 'issued' | 'delivered' | 'failed' | 'cancelled' | 'disputed';

export interface ChallengeHint {
  id: string;
  sort_order: number;
  body: string;
  released_at: string;
}

export interface RewardSummary {
  id: string;
  reward_type: RewardType;
  title: string;
  description: string | null;
  sponsor_name: string | null;
  quantity: number;
  terms_url: string | null;
}

export interface Participation {
  attempts_used: number;
  attempts_remaining: number;
  next_attempt_at: string | null;
  team_id: string | null;
  is_captain: boolean;
  status: 'active' | 'disqualified' | 'withdrawn';
}

/** Contract `Challenge` (member view: never any accepted answer, CHAL-008). */
export interface Challenge {
  id: string;
  group_id: string;
  kind: 'riddle';
  title: string;
  description: string;
  media: MediaRef | null;
  solving_mode: SolvingMode;
  validation_method: ValidationMethod;
  max_attempts: number;
  attempt_cooldown_seconds: number;
  winner_policy: WinnerPolicy;
  max_winners: number;
  prize_description: string | null;
  rewards: RewardSummary[];
  participation_rules: string | null;
  starts_at: string;
  ends_at: string;
  status: ChallengeStatus;
  published_at: string | null;
  results_published_at: string | null;
  rules_version: number;
  hints: ChallengeHint[];
  my_participation: Participation | null;
}

/** Contract `ChallengeManagerView` (the fields the app uses). */
export interface ChallengeManagerView extends Challenge {
  answer_count: number;
  participant_count: number;
  pending_review_count: number;
  version: number;
}

export interface SubmissionResult {
  submission_id: string;
  attempt_no: number;
  evaluation_status: EvaluationStatus;
  attempts_remaining: number;
  next_attempt_at: string | null;
  is_provisional_winner: boolean;
}

export interface ChallengeWinner {
  id: string;
  rank: number;
  user: UserSummary | null;
  team: { id: string; name: string } | null;
  status: 'provisional' | 'confirmed' | 'revoked';
  determined_by: 'system' | 'admin';
  determined_at: string;
}

export interface ChallengeResults {
  challenge_id: string;
  status: ChallengeStatus;
  published: boolean;
  results_published_at: string | null;
  participant_count: number;
  winners: ChallengeWinner[];
}

export interface ChallengeTeam {
  id: string;
  challenge_id: string;
  name: string;
  captain: UserSummary | null;
  members: UserSummary[];
  conversation_id: string | null;
  created_at: string;
}

export interface MyReward {
  fulfillment_id: string;
  challenge: { id: string; title: string; group_id: string };
  reward: RewardSummary;
  status: FulfillmentStatus;
  /** A discount code, shown only to the recipient once issued (CHAL-015). */
  secret: string | null;
  issued_at: string | null;
  delivered_at: string | null;
}

export interface NewChallenge {
  kind: 'riddle';
  title: string;
  description: string;
  solving_mode: SolvingMode;
  validation_method: ValidationMethod;
  accepted_answers: string[];
  hints: { body: string }[];
  starts_at: string;
  ends_at: string;
  max_attempts: number;
  winner_policy: WinnerPolicy;
  max_winners?: number;
  rewards: {
    reward_type: 'badge';
    title: string;
    badge_key: string;
    quantity: number;
    fulfillment_owner: 'platform';
  }[];
}

/** Contract `ChallengeSubmission` (AI fields only for judges). */
export interface ChallengeSubmission {
  id: string;
  challenge_id: string;
  submitted_by: UserSummary | null;
  team_id: string | null;
  attempt_no: number;
  answer_text: string;
  evaluation_status: EvaluationStatus;
  evaluator: 'exact' | 'ai' | 'admin' | null;
  ai_confidence?: number | null;
  ai_rationale?: string | null;
  submitted_at: string;
  evaluated_at: string | null;
}

export type Judgement = 'correct' | 'incorrect' | 'void';

export const challengeKeys = {
  group: (groupId: string) => ['challenges', 'group', groupId] as const,
  detail: (id: string) => ['challenges', 'detail', id] as const,
  manage: (id: string) => ['challenges', 'manage', id] as const,
  results: (id: string) => ['challenges', 'results', id] as const,
  teams: (id: string) => ['challenges', 'teams', id] as const,
  rewards: ['challenges', 'rewards'] as const,
  fulfillments: (id: string) => ['challenges', 'fulfillments', id] as const,
  review: (id: string) => ['challenges', 'review', id] as const,
};

/** Statuses in which a challenge is still open for teams and answers. */
export const OPEN_STATUSES: readonly ChallengeStatus[] = ['scheduled', 'active'];

/** A short machine key from a badge name ("Old Town Explorer" → "old-town-explorer"). */
export function badgeKey(name: string): string {
  const key = name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return key || 'challenge-badge';
}

export function listGroupChallenges(client: ApiClient, groupId: string): Promise<Page<Challenge>> {
  return client.get<Page<Challenge>>(`/v1/groups/${groupId}/challenges`, {
    query: { limit: 50 },
  });
}

export function getChallenge(client: ApiClient, id: string): Promise<Challenge> {
  return client.get<Challenge>(`/v1/challenges/${id}`);
}

export function getManagerView(client: ApiClient, id: string): Promise<ChallengeManagerView> {
  return client.get<ChallengeManagerView>(`/v1/challenges/${id}/manage`);
}

export function createChallenge(
  client: ApiClient,
  groupId: string,
  idempotencyKey: string,
  body: NewChallenge,
): Promise<ChallengeManagerView> {
  return client.post<ChallengeManagerView>(`/v1/groups/${groupId}/challenges`, {
    idempotencyKey,
    body,
  });
}

export function publishChallenge(
  client: ApiClient,
  id: string,
  version: number,
): Promise<ChallengeManagerView> {
  return client.post<ChallengeManagerView>(`/v1/challenges/${id}/publish`, {
    ifMatchVersion: version,
  });
}

export function submitAnswer(
  client: ApiClient,
  id: string,
  idempotencyKey: string,
  answer: string,
): Promise<SubmissionResult> {
  return client.post<SubmissionResult>(`/v1/challenges/${id}/submissions`, {
    idempotencyKey,
    body: { answer },
  });
}

export function getResults(client: ApiClient, id: string): Promise<ChallengeResults> {
  return client.get<ChallengeResults>(`/v1/challenges/${id}/results`);
}

export function publishResults(client: ApiClient, id: string): Promise<ChallengeResults> {
  return client.post<ChallengeResults>(`/v1/challenges/${id}/results/publish`);
}

export function listTeams(client: ApiClient, id: string): Promise<Page<ChallengeTeam>> {
  return client.get<Page<ChallengeTeam>>(`/v1/challenges/${id}/teams`, { query: { limit: 100 } });
}

export function createTeam(client: ApiClient, id: string, name: string): Promise<ChallengeTeam> {
  return client.post<ChallengeTeam>(`/v1/challenges/${id}/teams`, { body: { name } });
}

export function joinTeam(client: ApiClient, id: string, teamId: string): Promise<ChallengeTeam> {
  return client.post<ChallengeTeam>(`/v1/challenges/${id}/teams/${teamId}/join`);
}

export function listMyRewards(client: ApiClient): Promise<Page<MyReward>> {
  return client.get<Page<MyReward>>('/v1/users/me/rewards', { query: { limit: 50 } });
}

/** Answers waiting for a judge (SCR-090): pending and needs-review, oldest first. */
export async function listReviewQueue(
  client: ApiClient,
  id: string,
): Promise<ChallengeSubmission[]> {
  const pages = await Promise.all(
    (['pending', 'needs_review'] as const).map((evaluation_status) =>
      client.get<Page<ChallengeSubmission>>(`/v1/challenges/${id}/submissions`, {
        query: { scope: 'all', evaluation_status, limit: 100 },
      }),
    ),
  );
  return pages
    .flatMap((page) => page.data)
    .sort((a, b) => a.submitted_at.localeCompare(b.submitted_at));
}

export function judgeSubmission(
  client: ApiClient,
  challengeId: string,
  submissionId: string,
  evaluation: Judgement,
): Promise<ChallengeSubmission> {
  return client.post<ChallengeSubmission>(
    `/v1/challenges/${challengeId}/submissions/${submissionId}/judgement`,
    { body: { evaluation_status: evaluation } },
  );
}

export function updateWinner(
  client: ApiClient,
  challengeId: string,
  winnerId: string,
  action: 'confirm' | 'revoke',
): Promise<ChallengeWinner> {
  return client.post<ChallengeWinner>(
    `/v1/challenges/${challengeId}/winners/${winnerId}/${action}`,
  );
}

export function raiseDispute(
  client: ApiClient,
  challengeId: string,
  reason: string,
): Promise<unknown> {
  return client.post(`/v1/challenges/${challengeId}/disputes`, { body: { reason } });
}

/** Contract `RewardFulfillment` (never the code itself). */
export interface RewardFulfillment {
  id: string;
  challenge_reward_id: string;
  winner_id: string;
  recipient: UserSummary | null;
  status: FulfillmentStatus;
  issued_at: string | null;
  delivered_at: string | null;
  notes: string | null;
  updated_at: string;
}

/** The fulfillment state machine (CHAL-015), mirrored for the buttons; the server decides. */
export const FULFILLMENT_NEXT: Record<FulfillmentStatus, readonly FulfillmentStatus[]> = {
  pending: ['issued', 'failed', 'cancelled'],
  issued: ['delivered', 'failed', 'disputed'],
  failed: ['pending'],
  disputed: ['issued', 'cancelled'],
  delivered: [],
  cancelled: [],
};

export function listFulfillments(client: ApiClient, id: string): Promise<Page<RewardFulfillment>> {
  return client.get<Page<RewardFulfillment>>(`/v1/challenges/${id}/fulfillments`, {
    query: { limit: 100 },
  });
}

export function moveFulfillment(
  client: ApiClient,
  challengeId: string,
  fulfillmentId: string,
  body: { to_status: FulfillmentStatus; secret?: string; note?: string },
): Promise<RewardFulfillment> {
  return client.post<RewardFulfillment>(
    `/v1/challenges/${challengeId}/fulfillments/${fulfillmentId}/transitions`,
    { body },
  );
}

export interface ChallengeChanges {
  title?: string;
  description?: string;
  accepted_answers?: string[];
  starts_at?: string;
  ends_at?: string;
  max_attempts?: number;
  winner_policy?: WinnerPolicy;
}

/** Edit a draft (or extend a live challenge's end); needs the version read (If-Match). */
export function updateChallenge(
  client: ApiClient,
  id: string,
  version: number,
  body: ChallengeChanges,
): Promise<ChallengeManagerView> {
  return client.patch<ChallengeManagerView>(`/v1/challenges/${id}`, {
    body,
    ifMatchVersion: version,
  });
}

/** `POST /v1/challenges/{id}/cancel`: members are told; submissions stay for the audit. */
export async function cancelChallenge(
  client: ApiClient,
  id: string,
  reason: string,
): Promise<void> {
  await client.post(`/v1/challenges/${id}/cancel`, { body: { reason } });
}
