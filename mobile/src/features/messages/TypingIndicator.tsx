import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Animated, StyleSheet, Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';
import { useReduceMotion } from '@/theme/useReduceMotion';

const DOT_MS = 380;

function Dots() {
  const theme = useAppTheme();
  const reduceMotion = useReduceMotion();
  const [values] = useState(() => [0, 1, 2].map(() => new Animated.Value(0.35)));

  useEffect(() => {
    if (reduceMotion) return;
    const loop = Animated.loop(
      Animated.stagger(
        DOT_MS / 2,
        values.map((value) =>
          Animated.sequence([
            Animated.timing(value, { toValue: 1, duration: DOT_MS, useNativeDriver: true }),
            Animated.timing(value, { toValue: 0.35, duration: DOT_MS, useNativeDriver: true }),
          ]),
        ),
      ),
    );
    loop.start();
    return () => loop.stop();
  }, [reduceMotion, values]);

  return (
    <View style={styles.dots} accessibilityElementsHidden importantForAccessibility="no">
      {values.map((opacity, index) => (
        <Animated.View
          key={index}
          style={[styles.dot, { backgroundColor: theme.colors.primary, opacity }]}
        />
      ))}
    </View>
  );
}

/**
 * "Bo is typing…" under the newest message while the other side has the composer active
 * (docs/06 §4.1). Names come from the conversation; nothing shows when nobody is typing.
 */
export function TypingIndicator({ names }: { names: string[] }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  if (names.length === 0) return null;
  const text =
    names.length === 1
      ? t('messages.typingOne', { name: names[0] })
      : names.length === 2
        ? t('messages.typingTwo', { first: names[0], second: names[1] })
        : t('messages.typingMany', { count: names.length });
  return (
    <View
      style={[styles.row, { backgroundColor: theme.colors.surface }]}
      accessibilityRole="text"
      accessibilityLiveRegion="polite"
      accessibilityLabel={text}
      testID="chat-typing"
    >
      <Dots />
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  dots: { flexDirection: 'row', gap: 4 },
  dot: { width: 6, height: 6, borderRadius: 3 },
});
