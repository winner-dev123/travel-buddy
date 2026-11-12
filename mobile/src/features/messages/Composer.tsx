import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';

import type { SendSide } from '@/state/chatPreferences';
import { useAppTheme } from '@/theme/useAppTheme';

export interface ComposerProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  onPhoto: () => void;
  photoBusy: boolean;
  /** Right (the default) or left, for one-handed use with the left hand (SCR-119). */
  sendSide: SendSide;
  /** The emoji and gifts panel (DM-016): open or close it, and whether it's open. */
  onToggleTray?: () => void;
  trayOpen?: boolean;
  /** The text field got focus (the keyboard replaces the panel). */
  onFocusField?: () => void;
  placeholder?: string;
  testID?: string;
}

const BUTTON = 44;

/**
 * The message bar (SCR-081): the text field with the send button beside it on one line, and the
 * photo button on the opposite side. The field grows with the text up to a few lines; the emoji
 * and gifts button sits inside it, on the send button's side, within reach of the same thumb.
 */
export function Composer({
  value,
  onChangeText,
  onSend,
  onPhoto,
  photoBusy,
  sendSide,
  onToggleTray,
  trayOpen = false,
  onFocusField,
  placeholder,
  testID = 'chat-input',
}: ComposerProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const [focused, setFocused] = useState(false);
  const canSend = value.trim().length > 0;
  const label = placeholder ?? t('messages.placeholder');

  const photo = (
    <Pressable
      key="photo"
      onPress={onPhoto}
      disabled={photoBusy}
      accessibilityRole="button"
      accessibilityLabel={t('messages.sendPhoto')}
      accessibilityState={{ disabled: photoBusy, busy: photoBusy }}
      hitSlop={6}
      style={({ pressed }) => [styles.round, { opacity: pressed ? 0.6 : 1 }]}
      testID="chat-photo"
    >
      {photoBusy ? (
        <ActivityIndicator color={theme.colors.primary} />
      ) : (
        <Ionicons name="camera-outline" size={24} color={theme.colors.primary} />
      )}
    </Pressable>
  );

  const input = (
    <TextInput
      key="input"
      value={value}
      onChangeText={onChangeText}
      placeholder={label}
      accessibilityLabel={label}
      placeholderTextColor={theme.colors.textSecondary}
      selectionColor={theme.colors.primary}
      cursorColor={theme.colors.primary}
      maxLength={4000}
      multiline
      onFocus={() => {
        setFocused(true);
        onFocusField?.();
      }}
      onBlur={() => setFocused(false)}
      style={[theme.typography.body, styles.input, { color: theme.colors.textPrimary }]}
      testID={testID}
    />
  );

  const tray = onToggleTray ? (
    <Pressable
      key="tray"
      onPress={onToggleTray}
      accessibilityRole="button"
      accessibilityLabel={t('messages.expressions')}
      accessibilityState={{ expanded: trayOpen }}
      hitSlop={6}
      style={({ pressed }) => [styles.trayButton, { opacity: pressed ? 0.6 : 1 }]}
      testID="chat-tray"
    >
      <Ionicons
        name={trayOpen ? 'happy' : 'happy-outline'}
        size={24}
        color={trayOpen ? theme.colors.primary : theme.colors.textSecondary}
      />
    </Pressable>
  ) : null;

  const field = (
    <View
      key="field"
      style={[
        styles.field,
        {
          backgroundColor: theme.colors.surface,
          borderColor: focused || trayOpen ? theme.colors.primary : theme.colors.borderStrong,
        },
      ]}
      testID="chat-field"
    >
      {sendSide === 'right' ? [input, tray] : [tray, input]}
    </View>
  );

  const send = (
    <Pressable
      key="send"
      onPress={onSend}
      disabled={!canSend}
      accessibilityRole="button"
      accessibilityLabel={t('messages.send')}
      accessibilityState={{ disabled: !canSend }}
      hitSlop={6}
      style={({ pressed }) => [
        styles.round,
        styles.send,
        {
          backgroundColor: canSend ? theme.colors.primary : theme.colors.surfaceRaised,
          opacity: pressed ? 0.75 : 1,
        },
      ]}
      testID="chat-send"
    >
      <Ionicons
        name="send"
        size={20}
        color={canSend ? theme.colors.onPrimary : theme.colors.textSecondary}
      />
    </Pressable>
  );

  return (
    <View style={styles.row} testID="chat-composer">
      {sendSide === 'right' ? [photo, field, send] : [send, field, photo]}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: 8 },
  field: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-end',
    minHeight: BUTTON,
    borderWidth: 1,
    borderRadius: BUTTON / 2,
    paddingHorizontal: 6,
  },
  input: {
    flex: 1,
    maxHeight: 130,
    paddingHorizontal: 10,
    paddingTop: 10,
    paddingBottom: 10,
    textAlignVertical: 'center',
  },
  trayButton: { width: 34, height: BUTTON - 2, alignItems: 'center', justifyContent: 'center' },
  round: { width: BUTTON, height: BUTTON, alignItems: 'center', justifyContent: 'center' },
  send: { borderRadius: BUTTON / 2 },
});
