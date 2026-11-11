/** Response and request shapes of the admin API (contracts/openapi/openapi.yaml, Admin*). */

export type Uuid = string;
export type Timestamp = string;

export type PlatformRole = 'support' | 'moderator' | 'admin' | 'superadmin';
export const PLATFORM_ROLES: PlatformRole[] = ['support', 'moderator', 'admin', 'superadmin'];

export type Permission =
  | 'users.read'
  | 'users.read_sensitive'
  | 'users.suspend'
  | 'users.ban'
  | 'moderation.reports.read'
  | 'moderation.reports.manage'
  | 'moderation.actions.read'
  | 'moderation.actions.write'
  | 'content.destinations.write'
  | 'content.feature'
  | 'content.rewards.review'
  | 'entitlements.grant'
  | 'billing.configure'
  | 'audit.read'
  | 'privacy.requests.manage'
  | 'safety.filters.manage'
  | 'roles.assign';

export type AccountStatus = 'active' | 'suspended' | 'deactivated' | 'pending_deletion' | 'deleted';

export interface PageInfo {
  next_cursor: string | null;
  has_more: boolean;
}

export interface Page<T> {
  data: T[];
  page: PageInfo;
}

export interface SessionTokens {
  token_type: 'Bearer';
  access_token: string;
  access_token_expires_at: Timestamp;
  refresh_token: string;
  refresh_token_expires_at: Timestamp;
  session_id: Uuid;
}

/** The parts of `Me` the console uses. */
export interface Me {
  account: { id: Uuid; email: string | null; status: string; primary_locale: string };
  profile: { handle: string; display_name: string };
  roles: PlatformRole[];
  permissions?: Permission[];
}

export interface AuthResult {
  tokens: SessionTokens;
  user: Me;
  is_new_user: boolean;
}

export interface UserSummary {
  id: Uuid;
  handle: string;
  display_name: string;
}

export interface AdminUserSummary {
  id: Uuid;
  handle: string;
  display_name: string;
  status: AccountStatus;
  roles: PlatformRole[];
  created_at: Timestamp;
  last_active_on: string | null;
}

export interface AdminUser extends AdminUserSummary {
  email: string | null;
  open_report_count: number;
  moderation_action_count: number;
  suspended_until: Timestamp | null;
}

export interface AdminOverview {
  generated_at: Timestamp;
  users: { total: number; new_7d: number; new_30d: number; active_7d: number; suspended: number };
  premium_members: number;
  posts_7d: number;
  moderation: {
    open_reports: number;
    unassigned_reports: number;
    oldest_open_age_seconds: number | null;
    by_priority: Record<string, number>;
  };
  open_data_requests: number | null;
  revenue_30d: { currency: string; environment: 'production' | 'sandbox'; amount_minor: number }[] | null;
}

export interface OpsSummary {
  generated_at: Timestamp;
  moderation: Record<string, unknown>;
  outbox: { unpublished_events?: number; oldest_unpublished_age_seconds?: number | null };
  jobs: {
    queued_due?: number;
    running?: number;
    failed_last_24h?: number;
    oldest_due_age_seconds?: number | null;
  } & Record<string, unknown>;
}

export type ReportStatus = 'open' | 'in_review' | 'actioned' | 'dismissed';
export const REPORT_STATUSES: ReportStatus[] = ['open', 'in_review', 'actioned', 'dismissed'];
export type ReportTargetType = 'post' | 'comment' | 'user' | 'message' | 'group' | 'challenge' | 'media';
export const REPORT_TARGET_TYPES: ReportTargetType[] = [
  'post',
  'comment',
  'user',
  'message',
  'group',
  'challenge',
  'media',
];
export const REPORT_REASONS = [
  'spam',
  'harassment',
  'hate',
  'sexual_content',
  'minor_safety',
  'violence',
  'self_harm',
  'scam',
  'privacy_violation',
  'impersonation',
  'illegal',
  'other',
] as const;
export type ReportReason = (typeof REPORT_REASONS)[number];

export interface AdminReport {
  id: Uuid;
  reporter: UserSummary | null;
  target_type: ReportTargetType;
  target_id: Uuid;
  target_author: UserSummary | null;
  reason: ReportReason;
  details: string | null;
  priority: number;
  status: ReportStatus;
  assigned_to: UserSummary | null;
  evidence: Record<string, unknown>;
  resolution_note: string | null;
  related_report_count: number;
  created_at: Timestamp;
  resolved_at: Timestamp | null;
}

export type ModerationActionType =
  | 'remove_content'
  | 'restore_content'
  | 'limit_visibility'
  | 'warn'
  | 'restrict'
  | 'suspend'
  | 'ban'
  | 'reinstate'
  | 'remove_member';

export const RESTRICTION_KINDS = [
  'posting_limited',
  'commenting_limited',
  'messaging_limited',
  'connection_requests_limited',
  'discovery_disabled',
  'media_upload_limited',
] as const;
export type RestrictionKind = (typeof RESTRICTION_KINDS)[number];

export interface ModerationActionRequest {
  target_type: ReportTargetType;
  target_id: Uuid;
  action: ModerationActionType;
  reason_code: string;
  restriction_kind?: RestrictionKind;
  notes?: string;
  report_id?: Uuid;
  expires_at?: Timestamp;
}

export interface ModerationAction {
  id: Uuid;
  scope: 'platform' | 'group';
  group_id: Uuid | null;
  target_type: ReportTargetType;
  target_id: Uuid;
  action: ModerationActionType;
  restriction_kind: RestrictionKind | null;
  reason_code: string;
  notes: string | null;
  actor: UserSummary | null;
  report_id: Uuid | null;
  expires_at: Timestamp | null;
  created_at: Timestamp;
}

export interface EntitlementGrant {
  id: Uuid;
  user_id: Uuid | null;
  entitlement_key: string;
  source_type: 'promo' | 'admin_grant';
  starts_at: Timestamp;
  ends_at: Timestamp | null;
  revoked_at: Timestamp | null;
  created_at: Timestamp;
}

export type TransactionStatus = 'pending' | 'succeeded' | 'failed' | 'open' | 'won' | 'lost';
export const TRANSACTION_STATUSES: TransactionStatus[] = [
  'pending',
  'succeeded',
  'failed',
  'open',
  'won',
  'lost',
];

export interface AdminTransaction {
  id: Uuid;
  user_id: Uuid | null;
  provider: 'apple' | 'google' | 'stripe' | 'dev';
  environment: 'production' | 'sandbox';
  kind: 'payment' | 'refund' | 'dispute';
  status: TransactionStatus;
  amount_minor: number | null;
  currency: string | null;
  reason: string | null;
  provider_reference: string;
  product: { id: Uuid; kind: string; period: string | null; title: string | null } | null;
  occurred_at: Timestamp;
}

export type DataRequestKind = 'export' | 'deletion' | 'rectification';
export interface AdminDataRequest {
  id: Uuid;
  user_id: Uuid;
  kind: DataRequestKind;
  status: 'received' | 'processing' | 'completed' | 'rejected' | 'cancelled';
  channel: 'app' | 'email' | 'other';
  details: string | null;
  requested_at: Timestamp;
  due_at: Timestamp;
  overdue: boolean;
  scheduled_for: Timestamp | null;
  completed_at: Timestamp | null;
  handled_by: Uuid | null;
  resolution: string | null;
}

export interface AuditLogEntry {
  id: Uuid;
  occurred_at: Timestamp;
  actor_id: Uuid | null;
  actor_type: 'user' | 'admin' | 'system' | 'service';
  action: string;
  resource_type: string;
  resource_id: Uuid | null;
  scope_group_id: Uuid | null;
  request_id: string | null;
  metadata: Record<string, unknown>;
}

export interface AdminProduct {
  id: Uuid;
  sku: string;
  platform: 'ios' | 'android' | 'web';
  kind: 'auto_renewable' | 'non_renewing' | 'non_consumable';
  plan_key: 'premium' | null;
  period: string | null;
  entitlement_keys: string[];
  active: boolean;
  title?: Record<string, string>;
  description?: Record<string, string>;
  sort_order?: number;
}

export interface MessageFilterPolicy {
  terms: string[];
  new_connection_days: number;
  default_terms: string[];
  default_new_connection_days: number;
  version: number;
  updated_at: Timestamp | null;
  updated_by: Uuid | null;
}

export interface Problem {
  type?: string;
  title?: string;
  status: number;
  detail?: string;
  code: string;
  request_id?: string;
  errors?: { field: string; code: string; message: string }[];
}
