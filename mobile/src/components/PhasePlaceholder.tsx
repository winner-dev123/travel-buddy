import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getFeature, type FeatureKey } from '@/config/featureFlags';
import { useAppTheme } from '@/theme/useAppTheme';

import { OnlineOnlyBadge } from './OnlineOnlyBadge';

export interface PhasePlaceholderProps {
  feature: FeatureKey;
  /** Extra real content (e.g. safety guidance) rendered below the placeholder. */
  children?: ReactNode;
}

/**
 * The "Coming in Phase N" state for unreleased features. It deliberately shows
 * no sample or fake data, only what is planned and when.
 */
export function PhasePlaceholder({ feature, children }: PhasePlaceholderProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const definition = getFeature(feature);
  const capabilities = definition.plannedCapabilities;

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        testID={`phase-placeholder-${feature}`}
      >
        <Text
          accessibilityRole="header"
          style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
        >
          {t(`features.${feature}.title`)}
        </Text>

        <View
          style={[
            styles.phaseBanner,
            {
              backgroundColor: theme.colors.surface,
              borderColor: theme.colors.borderStrong,
              borderRadius: theme.radii.lg,
              padding: theme.spacing[4],
              gap: theme.spacing[2],
            },
          ]}
        >
          <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
            {t('placeholder.comingInPhase', { phase: definition.phase })}
          </Text>
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('placeholder.notAvailableYet')}
          </Text>
          {definition.requiresNetwork ? <OnlineOnlyBadge /> : null}
        </View>

        {capabilities.length > 0 ? (
          <View style={{ gap: theme.spacing[2] }}>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('placeholder.plannedCapabilities', { count: capabilities.length })}
            </Text>
            {capabilities.map((capabilityKey) => (
              <Text
                key={capabilityKey}
                style={[theme.typography.body, { color: theme.colors.textPrimary }]}
              >
                {'• '}
                {t(capabilityKey)}
              </Text>
            ))}
          </View>
        ) : null}

        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  phaseBanner: { borderWidth: StyleSheet.hairlineWidth * 2 },
});
