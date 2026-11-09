import { useTranslation } from 'react-i18next';
import { Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

const TIP_KEYS = [
  'safety.tipPublicPlaces',
  'safety.tipTellSomeone',
  'safety.tipPersonalDetails',
  'safety.tipCoarseLocation',
  'safety.tipBlockReport',
] as const;

/**
 * Safety guidance shown wherever traveler discovery can be enabled. Copy rule:
 * never describe meeting strangers as "safe" (master prompt §22).
 */
export function DiscoverySafetyNotice() {
  const { t } = useTranslation();
  const theme = useAppTheme();

  return (
    <View
      testID="discovery-safety-notice"
      style={{
        backgroundColor: theme.colors.warningSurface,
        borderRadius: theme.radii.lg,
        padding: theme.spacing[4],
        gap: theme.spacing[2],
      }}
    >
      <Text
        accessibilityRole="header"
        style={[theme.typography.title3, { color: theme.colors.onWarningSurface }]}
      >
        {t('safety.discoveryTitle')}
      </Text>
      <Text style={[theme.typography.body, { color: theme.colors.onWarningSurface }]}>
        {t('safety.discoveryIntro')}
      </Text>
      {TIP_KEYS.map((key) => (
        <Text key={key} style={[theme.typography.body, { color: theme.colors.onWarningSurface }]}>
          {'• '}
          {t(key)}
        </Text>
      ))}
      <Text style={[theme.typography.bodyStrong, { color: theme.colors.onWarningSurface }]}>
        {t('safety.guideWithoutDiscovery')}
      </Text>
    </View>
  );
}
