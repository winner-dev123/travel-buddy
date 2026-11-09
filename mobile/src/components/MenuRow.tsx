import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

export interface MenuRowProps {
  label: string;
  onPress: () => void;
  icon: ComponentProps<typeof Ionicons>['name'];
  detail?: string;
  destructive?: boolean;
  testID?: string;
}

/** A tappable settings row: icon, label, optional detail and a chevron. */
export function MenuRow({ label, onPress, icon, detail, destructive, testID }: MenuRowProps) {
  const theme = useAppTheme();
  const color = destructive ? theme.colors.danger : theme.colors.textPrimary;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={detail ? `${label}, ${detail}` : label}
      style={({ pressed }) => [
        styles.row,
        {
          borderBottomColor: theme.colors.divider,
          minHeight: theme.minTouchTarget + 8,
          opacity: pressed ? 0.7 : 1,
        },
      ]}
      testID={testID}
    >
      <Ionicons name={icon} size={22} color={color} />
      <Text style={[theme.typography.body, styles.label, { color }]}>{label}</Text>
      {detail ? (
        <View style={[styles.badge, { backgroundColor: theme.colors.primary }]}>
          <Text style={[theme.typography.caption, { color: theme.colors.onPrimary }]}>
            {detail}
          </Text>
        </View>
      ) : null}
      <Ionicons name="chevron-forward" size={18} color={theme.colors.textSecondary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderBottomWidth: 1,
    paddingVertical: 8,
  },
  label: { flex: 1 },
  badge: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
});
