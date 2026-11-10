import type { ApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Page, Post, UserSummary } from '@/features/feed/types';

export const accountKeys = {
  blocks: ['me', 'blocks'] as const,
  notifications: ['me', 'notifications'] as const,
  unread: ['me', 'notifications', 'unread'] as const,
  profile: (id: string) => ['user', id] as const,
  requests: (direction: 'incoming' | 'outgoing') =>
    ['me', 'connection-requests', direction] as const,
  connections: ['me', 'connections'] as const,
  posts: (id: string) => ['user', id, 'posts'] as const,
  dataRequests: ['me', 'data-requests'] as const,
  sessions: ['me', 'sessions'] as const,
  followRequests: ['me', 'follow-requests'] as const,
  entitlements: ['me', 'entitlements'] as const,
};

/** Re-read `Me` after a settings change so every screen shows the saved state. */
export async function refreshMe(client: ApiClient): Promise<Me> {
  const me = await client.get<Me>('/v1/users/me');
  useSessionStore.getState().setMe(me);
  return me;
}

export async function updateProfile(
  client: ApiClient,
  changes: Partial<{
    display_name: string;
    bio: string | null;
    account_visibility: 'public' | 'private';
  }>,
): Promise<Me> {
  const me = await client.patch<Me>('/v1/users/me', { body: changes });
  useSessionStore.getState().setMe(me);
  return me;
}

export async function updatePrivacy(
  client: ApiClient,
  changes: Partial<{ search_engine_indexing: boolean }>,
): Promise<Me> {
  await client.patch('/v1/users/me/privacy', { body: changes });
  return refreshMe(client);
}

export function listBlocks(client: ApiClient): Promise<Page<UserSummary>> {
  return client.get<Page<UserSummary>>('/v1/users/me/blocks', { query: { limit: 100 } });
}

export function block(client: ApiClient, userId: string): Promise<void> {
  return client.put(`/v1/users/${userId}/block`);
}

export function unblock(client: ApiClient, userId: string): Promise<void> {
  return client.delete(`/v1/users/${userId}/block`);
}

export interface DeletionRequest {
  id: string;
  status: string;
  scheduled_for: string | null;
}

export async function requestDeletion(
  client: ApiClient,
  reason: string,
  idempotencyKey: string,
): Promise<DeletionRequest> {
  const request = await client.post<DeletionRequest>('/v1/users/me/deletion', {
    idempotencyKey,
    body: { confirm: true, ...(reason.trim() ? { reason: reason.trim() } : {}) },
  });
  await refreshMe(client);
  return request;
}

/** Contract `DataSubjectRequest` (exports and deletions, AUTH-010/011). */
export interface DataRequest {
  id: string;
  kind: 'export' | 'deletion' | 'rectification';
  status: 'received' | 'processing' | 'completed' | 'rejected' | 'cancelled';
  requested_at: string;
  completed_at: string | null;
  scheduled_for?: string | null;
  download?: { url: string; expires_at: string } | null;
}

export function requestDataExport(client: ApiClient, idempotencyKey: string): Promise<DataRequest> {
  return client.post<DataRequest>('/v1/users/me/data-exports', { idempotencyKey });
}

export function listDataRequests(client: ApiClient): Promise<Page<DataRequest>> {
  return client.get<Page<DataRequest>>('/v1/users/me/data-requests', { query: { limit: 20 } });
}

export async function cancelDeletion(client: ApiClient): Promise<void> {
  await client.delete('/v1/users/me/deletion');
  await refreshMe(client);
}

export interface AppNotification {
  id: string;
  type: string;
  actor: UserSummary | null;
  entity_type: string | null;
  entity_id: string | null;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export function fetchNotifications(client: ApiClient): Promise<Page<AppNotification>> {
  return client.get<Page<AppNotification>>('/v1/notifications', { query: { limit: 50 } });
}

export async function unreadCount(client: ApiClient): Promise<number> {
  return (await client.get<{ count: number }>('/v1/notifications/unread-count')).count;
}

export function markAllRead(client: ApiClient): Promise<void> {
  return client.post('/v1/notifications/read', { body: { all: true } });
}

export interface PublicProfile {
  id: string;
  handle: string;
  display_name: string;
  avatar: UserSummary['avatar'];
  bio: string | null;
  account_visibility: 'public' | 'private';
  is_restricted: boolean;
  counts: { posts: number; followers: number; following: number } | null;
  follow_status: 'none' | 'following' | 'requested';
  relationship:
    'none' | 'request_pending' | 'request_received' | 'connected' | 'declined' | 'blocked';
  can_request_connection: boolean;
  can_message?: boolean;
  /** Non-transferable badges from challenges and the platform (CHAL-012). */
  badges?: { id: string; key: string; name: string }[];
}

export function fetchProfile(client: ApiClient, userId: string): Promise<PublicProfile> {
  return client.get<PublicProfile>(`/v1/users/${userId}`);
}

export function fetchUserPosts(client: ApiClient, userId: string): Promise<Page<Post>> {
  return client.get<Page<Post>>(`/v1/users/${userId}/posts`, { query: { limit: 20 } });
}

export async function setFollowing(
  client: ApiClient,
  userId: string,
  follow: boolean,
): Promise<'none' | 'following' | 'requested'> {
  if (!follow) {
    await client.delete(`/v1/users/${userId}/follow`);
    return 'none';
  }
  return (await client.put<{ status: 'following' | 'requested' }>(`/v1/users/${userId}/follow`))
    .status;
}

export type ReportTarget = 'post' | 'comment' | 'user' | 'message';
export const REPORT_REASONS = [
  'spam',
  'harassment',
  'hate',
  'scam',
  'impersonation',
  'sexual_content',
  'violence',
  'self_harm',
  'minor_safety',
  'privacy_violation',
  'illegal',
  'other',
] as const;
export type ReportReason = (typeof REPORT_REASONS)[number];

export function report(
  client: ApiClient,
  input: {
    targetType: ReportTarget;
    targetId: string;
    reason: ReportReason;
    details: string;
    alsoBlock: boolean;
  },
): Promise<{ id: string }> {
  return client.post<{ id: string }>('/v1/reports', {
    body: {
      target_type: input.targetType,
      target_id: input.targetId,
      reason: input.reason,
      also_block: input.alsoBlock,
      ...(input.details.trim() ? { details: input.details.trim() } : {}),
    },
  });
}

export interface ConnectionRequest {
  id: string;
  requester: UserSummary;
  recipient: UserSummary;
  status: 'pending' | 'accepted' | 'declined' | 'cancelled' | 'expired';
  note: string | null;
  created_at: string;
}

export interface Connection {
  user: UserSummary;
  connected_at: string;
}

export function sendConnectionRequest(
  client: ApiClient,
  recipientId: string,
  idempotencyKey: string,
  context: 'profile' | 'discovery' = 'profile',
): Promise<ConnectionRequest> {
  return client.post<ConnectionRequest>('/v1/connections/requests', {
    idempotencyKey,
    body: { recipient_id: recipientId, context },
  });
}

export function listConnectionRequests(
  client: ApiClient,
  direction: 'incoming' | 'outgoing',
): Promise<Page<ConnectionRequest>> {
  return client.get<Page<ConnectionRequest>>('/v1/connections/requests', {
    query: { direction, status: 'pending', limit: 50 },
  });
}

export function respondToRequest(
  client: ApiClient,
  requestId: string,
  action: 'accept' | 'decline' | 'cancel',
): Promise<unknown> {
  return client.post(`/v1/connections/requests/${requestId}/${action}`);
}

export function listConnections(client: ApiClient): Promise<Page<Connection>> {
  return client.get<Page<Connection>>('/v1/connections', { query: { limit: 100 } });
}

/** Contract `Session`: never carries IP addresses or tokens. */
export interface DeviceSession {
  id: string;
  platform: 'ios' | 'android' | 'web';
  device_name: string | null;
  app_version: string | null;
  created_at: string;
  last_used_at: string;
  is_current: boolean;
}

/** SCR-110: my signed-in devices. */
export async function listSessions(client: ApiClient): Promise<DeviceSession[]> {
  return (await client.get<{ data: DeviceSession[] }>('/v1/users/me/sessions')).data;
}

/** Signs that device out at its next token refresh. */
export async function revokeSession(client: ApiClient, sessionId: string): Promise<void> {
  await client.delete(`/v1/users/me/sessions/${sessionId}`);
}

export type QuotaKey =
  'ai.itinerary_generations' | 'ai.trip_replans' | 'offline.packages' | 'groups.owned';

export interface QuotaStatus {
  limit: number;
  used: number;
  resets_at: string | null;
}

/** Contract `Entitlements` (docs/07): for display only, the server re-checks every action. */
export interface Entitlements {
  plan: 'free' | 'premium';
  status:
    'none' | 'active' | 'in_grace_period' | 'in_billing_retry' | 'paused' | 'expired' | 'revoked';
  premium_until: string | null;
  store_grace_until: string | null;
  features: Record<string, boolean>;
  quotas: Record<QuotaKey, QuotaStatus>;
  active_subscription?: {
    provider: 'apple' | 'google' | 'stripe' | 'dev';
    product_id: string;
    auto_renew: boolean;
    management: 'app_store' | 'google_play' | 'stripe_portal';
  } | null;
}

export function fetchEntitlements(client: ApiClient): Promise<Entitlements> {
  return client.get<Entitlements>('/v1/billing/entitlements');
}

/** Pending follow requests to my private account (PROF-007). */
export function listFollowRequests(client: ApiClient): Promise<Page<UserSummary>> {
  return client.get<Page<UserSummary>>('/v1/users/me/follow-requests', { query: { limit: 50 } });
}

export async function answerFollowRequest(
  client: ApiClient,
  userId: string,
  approve: boolean,
): Promise<void> {
  await client.post(`/v1/users/me/follow-requests/${userId}/${approve ? 'approve' : 'decline'}`);
}
