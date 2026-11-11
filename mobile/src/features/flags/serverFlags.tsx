import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { APP_INFO_KEY, fetchAppInfo } from '@/auth/session';
import { Notice } from '@/components/Form';
import { useAppTheme } from '@/theme/useAppTheme';

/**
 * Server feature flags from `GET /v1/client-config` (BL-6.10). The API refuses a feature whose
 * flag is off (`403 feature_disabled`), so the app hides its entry points instead of offering
 * something that can only fail. This works alongside the build-time gate (`FeatureGate`).
 */
export type ServerFlag =
  | 'traveler_discovery'
  | 'connections'
  | 'direct_messages'
  | 'travel_groups'
  | 'billing'
  | 'trips'
  | 'guides'
  | 'offline_packages'
  | 'post_translation'
  | 'ai_itineraries'
  | 'ai_replanning'
  | 'group_challenges';

/**
 * `isOn(flag)`: a flag counts as on until the server says it is off, so a slow or failed config
 * load never hides a feature (the API still has the final word).
 */
export function useServerFlags(): (flag: ServerFlag) => boolean {
  const info = useQuery({
    queryKey: APP_INFO_KEY,
    queryFn: () => fetchAppInfo(getApiClient()),
    staleTime: 60_000, // a changed flag shows the next time the app comes to the foreground
  });
  const flags = info.data?.feature_flags;
  return (flag) => flags?.[flag] !== false;
}

export function isFeatureDisabled(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === 'feature_disabled';
}

export function FeatureUnavailable({ testID }: { testID?: string }) {
  const { t } = useTranslation();
  return (
    <Notice tone="info" testID={testID ?? 'feature-unavailable'}>
      {t('common.featureUnavailable')}
    </Notice>
  );
}

/** A whole screen that needs at least one of `anyOf`; otherwise a "not available" notice. */
export function ServerFeature({ anyOf, children }: { anyOf: ServerFlag[]; children: ReactNode }) {
  const theme = useAppTheme();
  const isOn = useServerFlags();
  if (anyOf.some(isOn)) {
    return <>{children}</>;
  }
  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4] }}>
        <FeatureUnavailable />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
