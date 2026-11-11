import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, type AccessibilityRole } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

export interface ChipProps {
  label: string;
  onPress: () => void;
  /** Selected chips are filled with the accent; omit for a plain action chip. */
  selected?: boolean;
  /** `filled` (default) for choices; `quiet` for secondary filters, which only tint. */
  tone?: 'filled' | 'quiet';
  icon?: ComponentProps<typeof Ionicons>['name'];
  /** `radio` or `tab` when the chip is one of a set; `button` otherwise. */
  accessibilityRole?: AccessibilityRole;
  testID?: string;
}

/** A pill: one choice in a set (tabs, filters, options) or a small action. */
export function Chip({
  label,
  onPress,
  selected,
  tone = 'filled',
  icon,
  accessibilityRole = 'button',
  testID,
}: ChipProps) {
  const theme = useAppTheme();
  const on = selected === true;
  const quiet = tone === 'quiet';
  const background = on
    ? quiet
      ? theme.colors.primaryMuted
      : theme.colors.primary
    : theme.colors.surface;
  const foreground = on
    ? quiet
      ? theme.colors.onPrimaryMuted
      : theme.colors.onPrimary
    : theme.colors.textPrimary;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={accessibilityRole}
      accessibilityState={selected === undefined ? undefined : { selected }}
      style={({ pressed }) => [
        styles.chip,
        quiet ? styles.quiet : null,
        {
          backgroundColor: background,
          borderColor: on ? (quiet ? theme.colors.primary : background) : theme.colors.divider,
          opacity: pressed ? 0.8 : 1,
        },
      ]}
      testID={testID}
    >
      {icon ? <Ionicons name={icon} size={15} color={foreground} accessible={false} /> : null}
      <Text
        style={[quiet ? theme.typography.caption : theme.typography.label, { color: foreground }]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
    minHeight: 38,
  },
  quiet: { paddingHorizontal: 14, paddingVertical: 7, minHeight: 34 },
});
