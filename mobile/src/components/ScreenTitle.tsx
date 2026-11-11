import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

export interface ScreenTitleProps {
  title: string;
  /** A short line above the title, e.g. the app name on Home. */
  eyebrow?: string;
  /** An action at the end of the row, e.g. the notifications bell. */
  trailing?: ReactNode;
  testID?: string;
}

/** The heading of a top-level screen: serif title over a short accent rule. */
export function ScreenTitle({ title, eyebrow, trailing, testID }: ScreenTitleProps) {
  const theme = useAppTheme();
  return (
    <View style={styles.row}>
      <View style={styles.text}>
        {eyebrow ? (
          <Text
            style={[theme.typography.overline, styles.eyebrow, { color: theme.colors.primary }]}
          >
            {eyebrow}
          </Text>
        ) : null}
        <Text
          accessibilityRole="header"
          style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
          testID={testID}
        >
          {title}
        </Text>
        <LinearGradient
          colors={theme.accentGradient}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={styles.rule}
        />
      </View>
      {trailing}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  text: { flex: 1, gap: 2 },
  eyebrow: { textTransform: 'uppercase' },
  rule: { width: 32, height: 2, borderRadius: 1, marginTop: 6 },
});
