import Ionicons from '@expo/vector-icons/Ionicons';
import { Children, type ComponentProps, type ReactNode } from 'react';
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

/** A tappable settings row: icon in a tinted well, label, optional detail and a chevron. */
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
          minHeight: theme.minTouchTarget + 12,
          paddingHorizontal: theme.spacing[4],
          backgroundColor: pressed ? theme.colors.surfaceRaised : 'transparent',
        },
      ]}
      testID={testID}
    >
      <View
        style={[
          styles.well,
          { backgroundColor: destructive ? theme.colors.surfaceRaised : theme.colors.primaryMuted },
        ]}
      >
        <Ionicons
          name={icon}
          size={18}
          color={destructive ? theme.colors.danger : theme.colors.onPrimaryMuted}
          accessible={false}
        />
      </View>
      <Text style={[theme.typography.body, styles.label, { color }]}>{label}</Text>
      {detail ? (
        <View style={[styles.badge, { backgroundColor: theme.colors.primary }]}>
          <Text style={[theme.typography.caption, { color: theme.colors.onPrimary }]}>
            {detail}
          </Text>
        </View>
      ) : null}
      <Ionicons
        name="chevron-forward"
        size={16}
        color={theme.colors.textSecondary}
        accessible={false}
      />
    </Pressable>
  );
}

/** A rounded card that groups related menu rows, with hairlines between them. */
export function MenuGroup({ title, children }: { title?: string; children: ReactNode }) {
  const theme = useAppTheme();
  const rows = Children.toArray(children);
  if (rows.length === 0) return null;
  return (
    <View style={{ gap: theme.spacing[2] }}>
      {title ? (
        <Text
          accessibilityRole="header"
          style={[
            theme.typography.overline,
            styles.groupTitle,
            { color: theme.colors.textSecondary, paddingHorizontal: theme.spacing[1] },
          ]}
        >
          {title}
        </Text>
      ) : null}
      <View
        style={[
          styles.group,
          {
            backgroundColor: theme.colors.surface,
            borderColor: theme.colors.divider,
            borderRadius: theme.radii.lg,
          },
        ]}
      >
        {rows.map((row, index) => (
          <View
            key={index}
            style={
              index > 0
                ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.divider }
                : null
            }
          >
            {row}
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8 },
  well: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: { flex: 1 },
  badge: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  group: { borderWidth: 1, overflow: 'hidden' },
  groupTitle: { textTransform: 'uppercase' },
});
