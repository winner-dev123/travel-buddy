import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

export interface ActionTileProps {
  label: string;
  icon: ComponentProps<typeof Ionicons>['name'];
  onPress: () => void;
  testID?: string;
}

/**
 * A secondary shortcut shown beside others in a row: icon in a tinted well over its label.
 * Tiles share the row equally, so long translations get the whole tile width to wrap in.
 */
export function ActionTile({ label, icon, onPress, testID }: ActionTileProps) {
  const theme = useAppTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [
        styles.tile,
        {
          minHeight: theme.minTouchTarget,
          padding: theme.spacing[3],
          gap: theme.spacing[2],
          borderRadius: theme.radii.lg,
          borderColor: theme.colors.divider,
          backgroundColor: pressed ? theme.colors.surfaceRaised : theme.colors.surface,
        },
      ]}
      testID={testID}
    >
      <View style={[styles.well, { backgroundColor: theme.colors.primaryMuted }]}>
        <Ionicons name={icon} size={18} color={theme.colors.onPrimaryMuted} accessible={false} />
      </View>
      <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: { flex: 1, borderWidth: StyleSheet.hairlineWidth },
  well: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
