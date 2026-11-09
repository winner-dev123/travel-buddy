import type { ReactNode } from 'react';

import { isFeatureEnabled, type FeatureKey } from '@/config/featureFlags';

import { PhasePlaceholder } from './PhasePlaceholder';

export interface FeatureGateProps {
  feature: FeatureKey;
  /** The real screen. Omit until it exists; the placeholder is shown instead. */
  children?: ReactNode;
  /** Extra content for the placeholder state (e.g. safety guidance). */
  placeholderExtra?: ReactNode;
  /** Injected in tests; defaults to build-time overrides. */
  overrides?: readonly string[];
}

/**
 * Renders `children` only when the feature is released (or force-enabled in a
 * development build) AND an implementation is provided. Otherwise it renders
 * the "Coming in Phase N" placeholder. Enabling a flag without an
 * implementation therefore never produces a blank or broken screen.
 */
export function FeatureGate({ feature, children, placeholderExtra, overrides }: FeatureGateProps) {
  const enabled = isFeatureEnabled(feature, overrides);
  if (enabled && children !== undefined) {
    return <>{children}</>;
  }
  return <PhasePlaceholder feature={feature}>{placeholderExtra}</PhasePlaceholder>;
}
