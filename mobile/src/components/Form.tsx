import Ionicons from '@expo/vector-icons/Ionicons';
import { LinearGradient } from 'expo-linear-gradient';
import { useState, type ComponentProps, type ReactNode } from 'react';
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

/** Accessible form primitives built on the design tokens (WCAG 2.2 AA pairs). */

type IoniconName = ComponentProps<typeof Ionicons>['name'];

export interface TextFieldProps extends Omit<TextInputProps, 'style'> {
  label: string;
  hint?: string;
  testID?: string;
}

export function TextField({ label, hint, testID, onFocus, onBlur, ...input }: TextFieldProps) {
  const theme = useAppTheme();
  const [focused, setFocused] = useState(false);
  return (
    <View style={{ gap: theme.spacing[2] }}>
      <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        accessibilityHint={hint}
        placeholderTextColor={theme.colors.textSecondary}
        selectionColor={theme.colors.primary}
        cursorColor={theme.colors.primary}
        testID={testID}
        onFocus={(event) => {
          setFocused(true);
          onFocus?.(event);
        }}
        onBlur={(event) => {
          setFocused(false);
          onBlur?.(event);
        }}
        style={[
          theme.typography.body,
          styles.input,
          {
            color: theme.colors.textPrimary,
            backgroundColor: theme.colors.surface,
            borderColor: focused ? theme.colors.primary : theme.colors.borderStrong,
            borderRadius: theme.radii.md,
            paddingHorizontal: theme.spacing[4],
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
  /** `primary`: the one main action (gold). `secondary`: a quiet filled button.
   * `ghost`: a text-only action for the least important choice on a screen. */
  variant?: 'primary' | 'secondary' | 'ghost';
  icon?: IoniconName;
  busy?: boolean;
  disabled?: boolean;
  testID?: string;
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  icon,
  busy = false,
  disabled = false,
  testID,
}: ButtonProps) {
  const theme = useAppTheme();
  const primary = variant === 'primary';
  const ghost = variant === 'ghost';
  const inactive = disabled || busy;
  const foreground = primary
    ? theme.colors.onPrimary
    : ghost
      ? theme.colors.primary
      : theme.colors.textPrimary;
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
        ghost ? styles.ghost : null,
        {
          backgroundColor: primary
            ? theme.colors.primary
            : ghost
              ? 'transparent'
              : theme.colors.surfaceRaised,
          borderColor: primary || ghost ? 'transparent' : theme.colors.divider,
          borderRadius: theme.radii.pill,
          paddingHorizontal: theme.spacing[5],
          opacity: inactive ? 0.5 : pressed ? 0.82 : 1,
        },
      ]}
    >
      {primary ? (
        <LinearGradient
          colors={theme.accentGradient}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={[StyleSheet.absoluteFill, { borderRadius: theme.radii.pill }]}
        />
      ) : null}
      {busy ? (
        <ActivityIndicator color={foreground} />
      ) : (
        <View style={styles.buttonContent}>
          {icon ? <Ionicons name={icon} size={18} color={foreground} accessible={false} /> : null}
          <Text style={[theme.typography.label, styles.buttonLabel, { color: foreground }]}>
            {label}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

const NOTICE_ICONS: Record<'error' | 'info' | 'success', IoniconName> = {
  error: 'alert-circle-outline',
  info: 'information-circle-outline',
  success: 'checkmark-circle-outline',
};

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
      style={[
        styles.notice,
        {
          backgroundColor: palette[0],
          borderRadius: theme.radii.md,
          padding: theme.spacing[3],
          gap: theme.spacing[2],
        },
      ]}
    >
      <Ionicons
        name={NOTICE_ICONS[tone]}
        size={20}
        color={palette[1]}
        style={styles.noticeIcon}
        accessible={false}
      />
      <Text style={[theme.typography.body, styles.flex, { color: palette[1] }]}>{children}</Text>
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
        thumbColor={theme.colors.surfaceRaised}
        ios_backgroundColor={theme.colors.borderStrong}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  input: { minHeight: 52, borderWidth: 1 },
  button: {
    minHeight: 52,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  ghost: { minHeight: 44 },
  buttonContent: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  buttonLabel: { fontSize: 15, letterSpacing: 0.3, textAlign: 'center' },
  notice: { flexDirection: 'row', alignItems: 'flex-start' },
  noticeIcon: { marginTop: 2 },
  switchRow: { flexDirection: 'row', alignItems: 'center', minHeight: 48 },
  flex: { flex: 1 },
});
