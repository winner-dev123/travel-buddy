import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

/** Minimal accessible form primitives built on the design tokens (WCAG 2.2 AA pairs). */

export interface TextFieldProps extends Omit<TextInputProps, 'style'> {
  label: string;
  hint?: string;
  testID?: string;
}

export function TextField({ label, hint, testID, ...input }: TextFieldProps) {
  const theme = useAppTheme();
  return (
    <View style={{ gap: theme.spacing[1] }}>
      <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        accessibilityHint={hint}
        placeholderTextColor={theme.colors.textSecondary}
        testID={testID}
        style={[
          theme.typography.body,
          styles.input,
          {
            color: theme.colors.textPrimary,
            backgroundColor: theme.colors.surfaceRaised,
            borderColor: theme.colors.borderStrong,
            borderRadius: theme.radii.md,
            paddingHorizontal: theme.spacing[3],
          },
        ]}
        {...input}
      />
      {hint ? (
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {hint}
        </Text>
      ) : null}
    </View>
  );
}

export interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary';
  busy?: boolean;
  disabled?: boolean;
  testID?: string;
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  busy = false,
  disabled = false,
  testID,
}: ButtonProps) {
  const theme = useAppTheme();
  const primary = variant === 'primary';
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: primary ? theme.colors.primary : theme.colors.surface,
          borderColor: primary ? theme.colors.primary : theme.colors.borderStrong,
          borderRadius: theme.radii.md,
          opacity: inactive ? 0.6 : pressed ? 0.85 : 1,
        },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={primary ? theme.colors.onPrimary : theme.colors.textPrimary} />
      ) : (
        <Text
          style={[
            theme.typography.label,
            { color: primary ? theme.colors.onPrimary : theme.colors.textPrimary },
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

export function Notice({
  tone,
  children,
  testID,
}: {
  tone: 'error' | 'info' | 'success';
  children: ReactNode;
  testID?: string;
}) {
  const theme = useAppTheme();
  const palette = {
    error: [theme.colors.warningSurface, theme.colors.onWarningSurface],
    info: [theme.colors.infoSurface, theme.colors.onInfoSurface],
    success: [theme.colors.successSurface, theme.colors.onSuccessSurface],
  }[tone];
  return (
    <View
      accessibilityLiveRegion="polite"
      accessibilityRole={tone === 'error' ? 'alert' : undefined}
      testID={testID}
      style={{
        backgroundColor: palette[0],
        borderRadius: theme.radii.md,
        padding: theme.spacing[3],
      }}
    >
      <Text style={[theme.typography.body, { color: palette[1] }]}>{children}</Text>
    </View>
  );
}

export function SwitchRow({
  label,
  value,
  onValueChange,
  testID,
}: {
  label: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  testID?: string;
}) {
  const theme = useAppTheme();
  return (
    <View style={[styles.switchRow, { gap: theme.spacing[3] }]}>
      <Text style={[theme.typography.body, styles.flex, { color: theme.colors.textPrimary }]}>
        {label}
      </Text>
      <Switch
        accessibilityLabel={label}
        accessibilityRole="switch"
        value={value}
        onValueChange={onValueChange}
        testID={testID}
        trackColor={{ true: theme.colors.primary, false: theme.colors.borderStrong }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  input: { minHeight: 48, borderWidth: 1 },
  button: { minHeight: 48, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  switchRow: { flexDirection: 'row', alignItems: 'center', minHeight: 48 },
  flex: { flex: 1 },
});
