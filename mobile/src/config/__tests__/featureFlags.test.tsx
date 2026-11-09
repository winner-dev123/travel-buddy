import { render, screen } from '@testing-library/react-native';
import { Text } from 'react-native';

import { FeatureGate } from '@/components/FeatureGate';
import { i18n } from '@/i18n';

import { normalizeBaseUrl } from '../env';
import { FEATURES, isFeatureEnabled, isFeatureKey, type FeatureKey } from '../featureFlags';

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

describe('feature flags', () => {
  it('releases only the features that are built (Phase 1 feed and onboarding)', () => {
    for (const key of Object.keys(FEATURES) as FeatureKey[]) {
      expect(isFeatureEnabled(key, [])).toBe(key === 'feed' || key === 'onboarding');
    }
  });

  it('honours development overrides', () => {
    expect(isFeatureEnabled('messaging', ['messaging'])).toBe(true);
    expect(isFeatureEnabled('explore', ['messaging'])).toBe(false);
  });

  it('every planned capability key resolves to a translation', () => {
    for (const definition of Object.values(FEATURES)) {
      for (const key of definition.plannedCapabilities) {
        expect(i18n.exists(key)).toBe(true);
      }
    }
  });

  it('recognises feature keys', () => {
    expect(isFeatureKey('feed')).toBe(true);
    expect(isFeatureKey('toString')).toBe(false);
  });
});

describe('FeatureGate', () => {
  it('shows the phase placeholder when the feature is not released', async () => {
    await render(
      <FeatureGate feature="messaging" overrides={[]}>
        <Text>real screen</Text>
      </FeatureGate>,
    );
    expect(screen.getByText('Coming in Phase 3')).toBeTruthy();
    expect(screen.queryByText('real screen')).toBeNull();
  });

  it('renders the implementation when force-enabled', async () => {
    await render(
      <FeatureGate feature="messaging" overrides={['messaging']}>
        <Text>real screen</Text>
      </FeatureGate>,
    );
    expect(screen.getByText('real screen')).toBeTruthy();
  });

  it('keeps the placeholder when enabled but not implemented yet', async () => {
    await render(<FeatureGate feature="explore" overrides={['explore']} />);
    expect(screen.getByText('Coming in Phase 4')).toBeTruthy();
  });

  it('does not label offline-capable features as online only', async () => {
    await render(<FeatureGate feature="offlineGuides" overrides={[]} />);
    expect(screen.queryByTestId('online-only-badge')).toBeNull();
  });
});

describe('normalizeBaseUrl', () => {
  it('strips trailing slashes and validates the scheme', () => {
    expect(normalizeBaseUrl(' https://api.example.test/// ')).toBe('https://api.example.test');
    expect(() => normalizeBaseUrl('api.example.test')).toThrow('must start with http');
  });
});
