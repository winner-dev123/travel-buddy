import { useTranslation } from 'react-i18next';
import { StyleSheet, Text, View } from 'react-native';

import { useIsOnline } from '@/offline/connectivity';
import { useAppTheme } from '@/theme/useAppTheme';

export interface OnlineOnlyBadgeProps {
  /** Overrides live connectivity (tests, previews). */
  online?: boolean;
}

/**
 * Labels a feature that needs connectivity (UX rule: features that do not work
 * offline must say so up front). When offline, it switches to a warning state.
 */
export function OnlineOnlyBadge({ online }: OnlineOnlyBadgeProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const liveOnline = useIsOnline();
  const isOnline = online ?? liveOnline;

  const background = isOnline ? theme.colors.infoSurface : theme.colors.warningSurface;
  const foreground = isOnline ? theme.colors.onInfoSurface : theme.colors.onWarningSurface;
  const label = isOnline ? t('offline.onlineOnly') : t('offline.offlineNow');
  const a11yLabel = isOnline ? t('offline.onlineOnlyA11y') : t('offline.offlineNowA11y');

  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={a11yLabel}
      testID="online-only-badge"
      style={[
        styles.badge,
        {
          backgroundColor: background,
          borderRadius: theme.radii.pill,
          paddingHorizontal: theme.spacing[3],
          paddingVertical: theme.spacing[1],
        },
      ]}
    >
      <Text style={[theme.typography.label, { color: foreground }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: 'flex-start',
  },
});
