import { useTranslation } from 'react-i18next';
import { Text, View } from 'react-native';

import { DiscoverySafetyNotice } from '@/components/DiscoverySafetyNotice';
import { FeatureGate } from '@/components/FeatureGate';
import { ONBOARDING_STEPS } from '@/features/onboarding/steps';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-010 Onboarding entry: lists the planned steps (Phase 1). */
export default function OnboardingScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();

  const extra = (
    <View style={{ gap: theme.spacing[4] }}>
      <View style={{ gap: theme.spacing[2] }}>
        <Text
          accessibilityRole="header"
          style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
        >
          {t('onboarding.stepsHeading')}
        </Text>
        {ONBOARDING_STEPS.map((step, index) => (
          <Text key={step.id} style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
            {`${index + 1}. `}
            {t(step.labelKey)}
          </Text>
        ))}
      </View>
      <DiscoverySafetyNotice />
    </View>
  );

  return <FeatureGate feature="onboarding" placeholderExtra={extra} />;
}
