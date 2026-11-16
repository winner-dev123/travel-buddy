import type { ApiClient } from '@/api';
import type { DestinationSummary, MediaRef, Page, UserSummary } from '@/features/feed/types';

/** Guides and travel companies (ADR-0036, docs/18). Contract tag `providers`. */

export type ProviderKind = 'guide' | 'company';
export type ProviderStatus =
  | 'draft'
  | 'submitted'
  | 'changes_requested'
  | 'approved'
  | 'rejected'
  | 'suspended'
  | 'deactivated';
export type ProviderRole = 'owner' | 'manager' | 'agent';
export type MemberStatus = 'invited' | 'active';
export const SPECIALTIES = [
  'city_tours',
  'history_culture',
  'food_drink',
  'nature',
  'adventure',
  'water_activities',
  'nightlife',
  'photography',
  'art_museums',
  'family',
  'wellness',
  'accessible_travel',
  'transfers',
  'multi_day',
] as const;
export type Specialty = (typeof SPECIALTIES)[number];
export const DOCUMENT_KINDS = [
  'identity',
  'tourism_registry',
  'guide_license',
  'business_registration',
  'insurance',
  'other',
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];
export const OFFERING_KINDS = [
  'tour',
  'activity',
  'transfer',
  'package',
  'class',
  'other',
] as const;
export type OfferingKind = (typeof OFFERING_KINDS)[number];
export type OfferingStatus = 'draft' | 'published' | 'archived' | 'removed';
export type PriceUnit = 'per_person' | 'per_group';
export type InquiryStatus =
  'open' | 'accepted' | 'declined' | 'withdrawn' | 'expired' | 'completed' | 'cancelled';
export type InquiryAction = 'accept' | 'decline' | 'complete' | 'cancel' | 'withdraw';
/** Languages offered as chips; the API accepts any BCP 47 language code. */
export const LANGUAGE_CHOICES = [
  'en',
  'pt',
  'es',
  'fr',
  'de',
  'it',
  'nl',
  'ja',
  'zh',
  'ar',
] as const;

/** Contract `ProviderSummary`. */
export interface ProviderSummary {
  id: string;
  slug: string;
  kind: ProviderKind;
  status: ProviderStatus;
  display_name: string;
  tagline: string | null;
  logo: MediaRef | null;
  cover: MediaRef | null;
  base_destination: DestinationSummary | null;
  languages: string[];
  specialties: Specialty[];
  rating_average: number | null;
  rating_count: number;
  verified_at: string | null;
  response_time_seconds: number | null;
}

/** Contract `ProviderProfile`. */
export interface ProviderProfile extends ProviderSummary {
  about: string | null;
  years_experience: number | null;
  website_url: string | null;
  service_areas: DestinationSummary[];
  published_offering_count: number;
  membership?: { role: ProviderRole; status: MemberStatus } | null;
}

/** Contract `ProviderWorkspace`: what the provider's own members see. */
export interface ProviderWorkspace extends ProviderProfile {
  country_code: string;
  legal_name: string | null;
  registration_number: string | null;
  review_note: string | null;
  suspended_reason: string | null;
  submitted_at: string | null;
  decided_at: string | null;
  locked_fields: string[];
  terms_version: string;
  terms_accepted_version: string | null;
  missing_for_submit: string[];
  inquiry_count: number;
  response_count: number;
  version: number;
  created_at: string;
}

export interface ProviderMembership {
  provider: ProviderSummary;
  role: ProviderRole;
  status: MemberStatus;
  invited_by: UserSummary | null;
  created_at: string;
}

export interface ProviderDocument {
  id: string;
  kind: DocumentKind;
  number: string | null;
  issuing_country: string | null;
  expires_on: string | null;
  status: 'pending' | 'accepted' | 'rejected';
  file_available: boolean;
  created_at: string;
  decided_at: string | null;
}

export interface ProviderMember {
  user: UserSummary | null;
  role: ProviderRole;
  status: MemberStatus;
  created_at: string;
  accepted_at: string | null;
}

/** Contract `Offering`. Prices are indicative "from" prices (phase 8a moves no money). */
export interface Offering {
  id: string;
  provider: ProviderSummary;
  status: OfferingStatus;
  kind: OfferingKind;
  title: string;
  description: string | null;
  destination: DestinationSummary | null;
  duration_minutes: number | null;
  price_from: { amount_minor: number; currency: string; unit: PriceUnit | null } | null;
  max_group_size: number | null;
  languages: string[];
  cover: MediaRef | null;
  published_at: string | null;
  version: number;
}

/** Contract `Inquiry`: a traveler's request, shown as a card in the provider chat. */
export interface Inquiry {
  id: string;
  provider: ProviderSummary;
  traveler: UserSummary | null;
  offering: { id: string; title: string; kind: OfferingKind } | null;
  start_date: string | null;
  end_date: string | null;
  flexible_dates: boolean;
  party_size: number;
  message: string;
  status: InquiryStatus;
  decline_reason: string | null;
  conversation_id: string | null;
  first_response_at: string | null;
  viewer_side: 'traveler' | 'provider';
  can_review: boolean;
  review_id: string | null;
  created_at: string;
  version: number;
}

export interface ProviderReview {
  id: string;
  provider_id: string;
  rating: number;
  body: string | null;
  /** Null once the author's account was erased ("Former traveler"). */
  author: UserSummary | null;
  reply: { body: string; replied_at: string } | null;
  created_at: string;
}

export interface ProviderFields {
  kind?: ProviderKind;
  display_name?: string;
  legal_name?: string | null;
  tagline?: string | null;
  about?: string | null;
  country_code?: string;
  base_destination_id?: string;
  languages?: string[];
  specialties?: Specialty[];
  years_experience?: number | null;
  website_url?: string | null;
  registration_number?: string | null;
  logo_media_id?: string | null;
  cover_media_id?: string | null;
}

export interface OfferingFields {
  kind?: OfferingKind;
  title?: string;
  description?: string | null;
  destination_id?: string;
  duration_minutes?: number | null;
  price_from_minor?: number | null;
  currency?: string | null;
  price_unit?: PriceUnit | null;
  max_group_size?: number | null;
  cover_media_id?: string | null;
}

export interface InquiryFields {
  offering_id?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  flexible_dates: boolean;
  party_size: number;
  message: string;
}

export const providerKeys = {
  all: ['providers'] as const,
  list: (destinationId: string | null, kind: ProviderKind | null) =>
    ['providers', 'list', destinationId ?? 'all', kind ?? 'any'] as const,
  profile: (id: string) => ['providers', 'profile', id] as const,
  offerings: (id: string, all: boolean) => ['providers', 'offerings', id, all] as const,
  offering: (id: string) => ['providers', 'offering', id] as const,
  reviews: (id: string) => ['providers', 'reviews', id] as const,
  mine: ['providers', 'mine'] as const,
  workspace: (id: string) => ['providers', 'workspace', id] as const,
  documents: (id: string) => ['providers', 'documents', id] as const,
  members: (id: string) => ['providers', 'members', id] as const,
  inbox: (id: string, status: InquiryStatus | null) =>
    ['providers', 'inbox', id, status ?? 'all'] as const,
  myRequests: ['providers', 'my-requests'] as const,
  request: (id: string) => ['providers', 'request', id] as const,
};

// ───────────────────────────── browsing ─────────────────────────────

export function listProviders(
  client: ApiClient,
  filters: { destinationId?: string | null; kind?: ProviderKind | null; limit?: number },
): Promise<Page<ProviderSummary>> {
  return client.get<Page<ProviderSummary>>('/v1/providers', {
    query: {
      destination_id: filters.destinationId ?? undefined,
      kind: filters.kind ?? undefined,
      limit: filters.limit ?? 20,
    },
  });
}

export function getProvider(client: ApiClient, id: string): Promise<ProviderProfile> {
  return client.get<ProviderProfile>(`/v1/providers/${id}`);
}

export function listOfferings(
  client: ApiClient,
  providerId: string,
  all = false,
): Promise<Page<Offering>> {
  return client.get<Page<Offering>>(`/v1/providers/${providerId}/offerings`, {
    query: { status: all ? 'all' : 'published', limit: 50 },
  });
}

export function getOffering(client: ApiClient, id: string): Promise<Offering> {
  return client.get<Offering>(`/v1/provider-offerings/${id}`);
}

export function listReviews(client: ApiClient, providerId: string): Promise<Page<ProviderReview>> {
  return client.get<Page<ProviderReview>>(`/v1/providers/${providerId}/reviews`, {
    query: { limit: 20 },
  });
}

export function blockProvider(client: ApiClient, providerId: string): Promise<void> {
  return client.put(`/v1/providers/${providerId}/block`);
}

// ───────────────────────────── applying ─────────────────────────────

export function listMyProviders(client: ApiClient): Promise<{ data: ProviderMembership[] }> {
  return client.get<{ data: ProviderMembership[] }>('/v1/users/me/providers');
}

export function createProvider(
  client: ApiClient,
  idempotencyKey: string,
  body: ProviderFields,
): Promise<ProviderWorkspace> {
  return client.post<ProviderWorkspace>('/v1/providers', { idempotencyKey, body });
}

export function getWorkspace(client: ApiClient, id: string): Promise<ProviderWorkspace> {
  return client.get<ProviderWorkspace>(`/v1/providers/${id}/workspace`);
}

export function updateProvider(
  client: ApiClient,
  id: string,
  version: number,
  body: ProviderFields,
): Promise<ProviderWorkspace> {
  return client.patch<ProviderWorkspace>(`/v1/providers/${id}`, { body, ifMatchVersion: version });
}

export function setServiceAreas(
  client: ApiClient,
  id: string,
  destinationIds: string[],
): Promise<ProviderWorkspace> {
  return client.put<ProviderWorkspace>(`/v1/providers/${id}/service-areas`, {
    body: { destination_ids: destinationIds },
  });
}

export function listDocuments(
  client: ApiClient,
  id: string,
): Promise<{ data: ProviderDocument[] }> {
  return client.get<{ data: ProviderDocument[] }>(`/v1/providers/${id}/documents`);
}

export function addDocument(
  client: ApiClient,
  id: string,
  body: { kind: DocumentKind; media_id: string; number?: string },
): Promise<ProviderDocument> {
  return client.post<ProviderDocument>(`/v1/providers/${id}/documents`, { body });
}

export function deleteDocument(client: ApiClient, id: string, documentId: string): Promise<void> {
  return client.delete(`/v1/providers/${id}/documents/${documentId}`);
}

export function submitProvider(
  client: ApiClient,
  id: string,
  termsVersion: string,
): Promise<ProviderWorkspace> {
  return client.post<ProviderWorkspace>(`/v1/providers/${id}/submit`, {
    body: { terms_version: termsVersion },
  });
}

export function deactivateProvider(client: ApiClient, id: string): Promise<ProviderWorkspace> {
  return client.post<ProviderWorkspace>(`/v1/providers/${id}/deactivate`);
}

// ───────────────────────────── team ─────────────────────────────

export function listMembers(client: ApiClient, id: string): Promise<{ data: ProviderMember[] }> {
  return client.get<{ data: ProviderMember[] }>(`/v1/providers/${id}/members`);
}

export function inviteMember(
  client: ApiClient,
  id: string,
  handle: string,
  role: 'manager' | 'agent',
): Promise<{ data: ProviderMember[] }> {
  return client.post<{ data: ProviderMember[] }>(`/v1/providers/${id}/members`, {
    body: { handle: handle.replace(/^@/, '').trim(), role },
  });
}

export function acceptInvitation(client: ApiClient, id: string): Promise<ProviderWorkspace> {
  return client.post<ProviderWorkspace>(`/v1/providers/${id}/members/me/accept`);
}

export function removeMember(client: ApiClient, id: string, userId: string): Promise<void> {
  return client.delete(`/v1/providers/${id}/members/${userId}`);
}

// ───────────────────────────── offerings ─────────────────────────────

export function createOffering(
  client: ApiClient,
  providerId: string,
  body: OfferingFields,
): Promise<Offering> {
  return client.post<Offering>(`/v1/providers/${providerId}/offerings`, { body });
}

export function updateOffering(
  client: ApiClient,
  id: string,
  version: number,
  body: OfferingFields,
): Promise<Offering> {
  return client.patch<Offering>(`/v1/provider-offerings/${id}`, { body, ifMatchVersion: version });
}

export function setOfferingLive(client: ApiClient, id: string, live: boolean): Promise<Offering> {
  return client.post<Offering>(`/v1/provider-offerings/${id}/${live ? 'publish' : 'archive'}`);
}

// ───────────────────────────── requests ─────────────────────────────

export function sendRequest(
  client: ApiClient,
  providerId: string,
  idempotencyKey: string,
  body: InquiryFields,
): Promise<Inquiry> {
  return client.post<Inquiry>(`/v1/providers/${providerId}/inquiries`, { idempotencyKey, body });
}

export function listMyRequests(client: ApiClient): Promise<Page<Inquiry>> {
  return client.get<Page<Inquiry>>('/v1/users/me/inquiries', { query: { limit: 50 } });
}

export function listInbox(
  client: ApiClient,
  providerId: string,
  status: InquiryStatus | null,
): Promise<Page<Inquiry>> {
  return client.get<Page<Inquiry>>(`/v1/providers/${providerId}/inquiries`, {
    query: { status: status ?? undefined, limit: 50 },
  });
}

export function getRequest(client: ApiClient, id: string): Promise<Inquiry> {
  return client.get<Inquiry>(`/v1/provider-inquiries/${id}`);
}

export function actOnRequest(
  client: ApiClient,
  id: string,
  action: InquiryAction,
  reason?: string,
): Promise<Inquiry> {
  return client.post<Inquiry>(`/v1/provider-inquiries/${id}/${action}`, {
    body: action === 'decline' && reason ? { reason } : undefined,
  });
}

export function reviewRequest(
  client: ApiClient,
  id: string,
  rating: number,
  body: string,
): Promise<ProviderReview> {
  return client.post<ProviderReview>(`/v1/provider-inquiries/${id}/review`, {
    body: { rating, body: body.trim() || null },
  });
}

/** What each side may do in each status (mirrors the backend state machine, docs/18 §2.2). */
export function actionsFor(inquiry: Pick<Inquiry, 'status' | 'viewer_side'>): InquiryAction[] {
  const provider = inquiry.viewer_side === 'provider';
  if (inquiry.status === 'open') return provider ? ['accept', 'decline'] : ['withdraw'];
  if (inquiry.status === 'accepted') return provider ? ['complete', 'cancel'] : ['cancel'];
  return [];
}

/** The requests that belong to one provider chat (latest first), from the viewer's own lists. */
export async function requestsForChat(
  client: ApiClient,
  chat: { provider_id?: string | null; counterpart: UserSummary | null },
): Promise<Inquiry[]> {
  const providerId = chat.provider_id;
  if (!providerId) return [];
  if (chat.counterpart) {
    const inbox = await listInbox(client, providerId, null);
    return inbox.data.filter((i) => i.traveler?.id === chat.counterpart?.id);
  }
  const mine = await listMyRequests(client);
  return mine.data.filter((i) => i.provider.id === providerId);
}
