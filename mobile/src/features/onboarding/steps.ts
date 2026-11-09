import type { ParseKeys } from 'i18next';

/**
 * Onboarding order (docs/03 §4). Optional steps can be skipped. Location
 * permission and traveler discovery are separate consents, and discovery
 * defaults to OFF.
 */
export interface OnboardingStep {
  id: string;
  labelKey: ParseKeys;
  optional: boolean;
}

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  { id: 'account', labelKey: 'onboarding.steps.account', optional: false },
  { id: 'age-terms', labelKey: 'onboarding.steps.ageTerms', optional: false },
  { id: 'profile', labelKey: 'onboarding.steps.profile', optional: false },
  { id: 'language', labelKey: 'onboarding.steps.language', optional: false },
  { id: 'interests', labelKey: 'onboarding.steps.interests', optional: true },
  { id: 'destination', labelKey: 'onboarding.steps.destination', optional: true },
  { id: 'location', labelKey: 'onboarding.steps.location', optional: true },
  { id: 'discovery', labelKey: 'onboarding.steps.discovery', optional: true },
];
