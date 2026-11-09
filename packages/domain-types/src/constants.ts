/**
 * Runtime enum arrays for UI and validation. `satisfies` ties each list to the generated contract
 * type, so an enum change in openapi.yaml becomes a compile error here instead of a silent drift.
 */
import type {
  ContractErrorCode,
  Entitlements,
  FeatureKey,
  FeedTab,
  PlatformRole,
  PostKind,
  PostVisibility,
  ReactionType,
  ReportReason,
  TravelStyle,
} from './contract';

export const SUPPORTED_LOCALES = ['en', 'es', 'pt-BR', 'fr', 'de'] as const;
export type LocaleCode = (typeof SUPPORTED_LOCALES)[number];

export const FEED_TABS = ['for_you', 'nearby', 'following', 'destinations'] as const satisfies readonly FeedTab[];

/** Nearby radius choices offered in the UI (contract allows 1–50 km, default 10). */
export const FEED_RADII_KM = [5, 10, 25, 50] as const;
export type FeedRadiusKm = (typeof FEED_RADII_KM)[number];

export const REACTION_TYPES = ['like', 'love', 'helpful', 'wow'] as const satisfies readonly ReactionType[];

export const POST_VISIBILITIES = ['public', 'followers', 'connections', 'private'] as const satisfies readonly PostVisibility[];

export const POST_KINDS = [
  'text',
  'photo',
  'video',
  'story',
  'attraction_recommendation',
  'restaurant_recommendation',
  'review',
  'tip',
  'itinerary_summary',
  'experience',
] as const satisfies readonly PostKind[];

export const TRAVEL_STYLES = [
  'adventure',
  'backpacking',
  'luxury',
  'food',
  'culture',
  'photography',
  'digital_nomad',
  'nature',
  'family',
] as const satisfies readonly TravelStyle[];

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
] as const satisfies readonly ReportReason[];

export const PLATFORM_ROLES = ['support', 'moderator', 'admin', 'superadmin'] as const satisfies readonly PlatformRole[];

export const FEATURE_KEYS = [
  'groups.create',
  'challenges.create',
  'guides.premium',
  'audio_tours.premium',
  'ai.trip_replan',
] as const satisfies readonly FeatureKey[];

/** Codes reserved for web/BFF/client/mock use. Never emitted by the backend (doc 05). */
export type ReservedErrorCode = 'csrf_failed' | 'network_error' | 'feature_not_available_in_mock';

/** `string & {}` keeps autocomplete while tolerating codes added later (doc 05 §9). */
export type ErrorCode = ContractErrorCode | ReservedErrorCode | (string & {});

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  code: ErrorCode;
  request_id?: string;
  errors?: { field: string; code: string; message: string }[];
  /** `entitlement_required` → the feature (doc 07 §7). */
  feature_key?: string;
  [extension: string]: unknown;
}

export function hasFeature(entitlements: Entitlements | null | undefined, key: FeatureKey): boolean {
  return entitlements?.features[key] === true;
}
