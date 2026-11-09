import type { ParseKeys } from 'i18next';

import { getFeatureFlagOverrides } from './env';

/** Delivery phases from the master plan (docs/09-development-backlog.md). */
export type DeliveryPhase = 1 | 2 | 3 | 4 | 5 | 6 | 7;

export type FeatureKey =
  | 'auth'
  | 'onboarding'
  | 'feed'
  | 'explore'
  | 'companions'
  | 'messaging'
  | 'profile'
  | 'discovery'
  | 'groups'
  | 'challenges'
  | 'aiItinerary'
  | 'offlineGuides'
  | 'subscriptions';

/** Full translation key of a planned capability (type-checked against en.json). */
export type CapabilityKey = ParseKeys;

export interface FeatureDefinition {
  /** Phase in which the feature is scheduled to ship. */
  phase: DeliveryPhase;
  /**
   * `true` only when the real implementation is merged and released. Nothing is
   * released in Phase 0, so every screen renders its "Coming in Phase N" state.
   */
  released: boolean;
  /** Shown with an "Online only" badge when it needs connectivity. */
  requiresNetwork: boolean;
  /** Planned capabilities listed on the placeholder (translation keys). */
  plannedCapabilities: readonly CapabilityKey[];
}

export const FEATURES: Readonly<Record<FeatureKey, FeatureDefinition>> = {
  auth: {
    phase: 1,
    released: false,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.auth.capabilities.emailSignIn',
      'features.auth.capabilities.sessions',
      'features.auth.capabilities.verification',
    ],
  },
  onboarding: {
    phase: 1,
    released: false,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.onboarding.capabilities.profileBasics',
      'features.onboarding.capabilities.interests',
      'features.onboarding.capabilities.destination',
    ],
  },
  feed: {
    phase: 1,
    released: true,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.feed.capabilities.localFeed',
      'features.feed.capabilities.filters',
      'features.feed.capabilities.interactions',
    ],
  },
  explore: {
    phase: 4,
    released: false,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.explore.capabilities.map',
      'features.explore.capabilities.attractions',
      'features.explore.capabilities.assistant',
    ],
  },
  companions: {
    phase: 2,
    released: false,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.companions.capabilities.discovery',
      'features.companions.capabilities.requests',
      'features.companions.capabilities.groups',
    ],
  },
  messaging: {
    phase: 3,
    released: false,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.messaging.capabilities.direct',
      'features.messaging.capabilities.groups',
      'features.messaging.capabilities.activities',
    ],
  },
  profile: {
    phase: 1,
    released: false,
    requiresNetwork: true,
    plannedCapabilities: [
      'features.profile.capabilities.posts',
      'features.profile.capabilities.trips',
      'features.profile.capabilities.privacy',
    ],
  },
  discovery: { phase: 2, released: false, requiresNetwork: true, plannedCapabilities: [] },
  groups: { phase: 3, released: false, requiresNetwork: true, plannedCapabilities: [] },
  challenges: { phase: 5, released: false, requiresNetwork: true, plannedCapabilities: [] },
  aiItinerary: { phase: 4, released: false, requiresNetwork: true, plannedCapabilities: [] },
  // Downloaded guides and audio tours work offline once fetched.
  offlineGuides: { phase: 4, released: false, requiresNetwork: false, plannedCapabilities: [] },
  subscriptions: { phase: 3, released: false, requiresNetwork: true, plannedCapabilities: [] },
};

export function isFeatureKey(value: string): value is FeatureKey {
  return Object.prototype.hasOwnProperty.call(FEATURES, value);
}

/**
 * Whether a feature's real UI may be shown. Development builds may force-enable
 * features via `EXPO_PUBLIC_FEATURE_FLAGS` (see `.env.example`); the server
 * remains the authority for anything entitlement- or permission-gated.
 */
export function isFeatureEnabled(
  key: FeatureKey,
  overrides: readonly string[] = getFeatureFlagOverrides(),
): boolean {
  return FEATURES[key].released || overrides.includes(key);
}

export function getFeature(key: FeatureKey): FeatureDefinition {
  return FEATURES[key];
}
