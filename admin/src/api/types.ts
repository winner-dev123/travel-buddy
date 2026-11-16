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
  | 'roles.assign'
  | 'providers.verify';

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
export type ReportTargetType =
  | 'post'
  | 'comment'
  | 'user'
  | 'message'
  | 'group'
  | 'challenge'
  | 'media'
  | 'provider'
  | 'provider_offering'
  | 'provider_review';
export const REPORT_TARGET_TYPES: ReportTargetType[] = [
  'post',
  'comment',
  'user',
  'message',
  'group',
  'challenge',
  'media',
  'provider',
  'provider_offering',
  'provider_review',
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

// ───────── Guides and travel companies (ADR-0036) ─────────

export type ProviderKind = 'guide' | 'company';
export const PROVIDER_KINDS: ProviderKind[] = ['guide', 'company'];
export type ProviderStatus =
  | 'draft'
  | 'submitted'
  | 'changes_requested'
  | 'approved'
  | 'rejected'
  | 'suspended'
  | 'deactivated';
export const PROVIDER_STATUSES: ProviderStatus[] = [
  'draft',
  'submitted',
  'changes_requested',
  'approved',
  'rejected',
  'suspended',
  'deactivated',
];
export type ProviderRole = 'owner' | 'manager' | 'agent';
export type ProviderMemberStatus = 'invited' | 'active';
export type ProviderSpecialty =
  | 'city_tours'
  | 'history_culture'
  | 'food_drink'
  | 'nature'
  | 'adventure'
  | 'water_activities'
  | 'nightlife'
  | 'photography'
  | 'art_museums'
  | 'family'
  | 'wellness'
  | 'accessible_travel'
  | 'transfers'
  | 'multi_day';
export type ProviderDocumentKind =
  | 'identity'
  | 'tourism_registry'
  | 'guide_license'
  | 'business_registration'
  | 'insurance'
  | 'other';
export type ProviderDocumentStatus = 'pending' | 'accepted' | 'rejected';

/** The parts of `MediaRef` the console uses. */
export interface MediaRef {
  id: Uuid;
  kind: 'image' | 'video' | 'audio';
  status: 'ready' | 'processing' | 'unavailable';
  url: string | null;
  url_expires_at: Timestamp | null;
  alt_text?: string | null;
}

/** The parts of `DestinationSummary` the console uses. */
export interface DestinationSummary {
  id: Uuid;
  kind: string;
  slug: string;
  path: string;
  name: string;
  country_code: string;
  country_name?: string | null;
  region_name?: string | null;
}

export interface AdminProviderSummary {
  id: Uuid;
  kind: ProviderKind;
  status: ProviderStatus;
  display_name: string;
  country_code: string;
  owner: UserSummary | null;
  submitted_at: Timestamp | null;
  decided_at: Timestamp | null;
  created_at: Timestamp;
}

/** `ProviderWorkspace`: the public profile plus the private verification fields. */
export interface ProviderWorkspace {
  id: Uuid;
  slug: string;
  kind: ProviderKind;
  status: ProviderStatus;
  display_name: string;
  tagline: string | null;
  logo: MediaRef | null;
  cover: MediaRef | null;
  base_destination: DestinationSummary | null;
  languages: string[];
  specialties: ProviderSpecialty[];
  rating_average: number | null;
  rating_count: number;
  verified_at: Timestamp | null;
  response_time_seconds: number | null;
  about: string | null;
  years_experience: number | null;
  website_url: string | null;
  service_areas: DestinationSummary[];
  published_offering_count: number;
  country_code: string;
  legal_name: string | null;
  registration_number: string | null;
  review_note: string | null;
  suspended_reason: string | null;
  submitted_at: Timestamp | null;
  decided_at: Timestamp | null;
  locked_fields: string[];
  terms_version: string;
  terms_accepted_version: string | null;
  missing_for_submit: string[];
  inquiry_count: number;
  response_count: number;
  version: number;
  created_at: Timestamp;
}

export interface ProviderMember {
  user: UserSummary | null;
  role: ProviderRole;
  status: ProviderMemberStatus;
  created_at: Timestamp;
  accepted_at: Timestamp | null;
}

export interface AdminProviderDocument {
  id: Uuid;
  kind: ProviderDocumentKind;
  number: string | null;
  issuing_country: string | null;
  /** A local date, `2027-05-31`. */
  expires_on: string | null;
  status: ProviderDocumentStatus;
  /** Files are deleted 90 days after the decision; the record of the check stays. */
  file_available: boolean;
  created_at: Timestamp;
  decided_at: Timestamp | null;
  decided_by: Uuid | null;
  uploaded_by: Uuid | null;
}

export interface AdminProvider {
  provider: ProviderWorkspace;
  owner: UserSummary | null;
  members: ProviderMember[];
  documents: AdminProviderDocument[];
  decided_by: Uuid | null;
  open_report_count: number;
}

/** A 5-minute signed link to a verification document; each opening is audited. */
export interface ProviderDocumentFileLink {
  url: string;
  expires_at: Timestamp;
}

export type ProviderDecision = 'approve' | 'request_changes' | 'reject';

export interface ProviderDecisionRequest {
  decision: ProviderDecision;
  /** Required unless approving; shown to the applicant. */
  note?: string;
  /** On approval, documents not listed are accepted. */
  documents?: { id: Uuid; status: 'accepted' | 'rejected' }[];
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
