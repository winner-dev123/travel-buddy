import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Animated, Pressable, StyleSheet, Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';
import { useReduceMotion } from '@/theme/useReduceMotion';

import type { MessageGift } from './api';
import { GIFT_EFFECT_ICONS, giftEffectOf, giftImage, giftNameKey, WRAPPED_GIFT } from './gifts';

export interface GiftBubbleProps {
  gift: MessageGift;
  /** I sent it: shown open, with whether the other person has opened it yet. */
  mine: boolean;
  /** The sender, for "Lucas sent you a gift". */
  senderName: string;
  /** Unwrap (the recipient only). */
  onOpen?: () => void;
  opening?: boolean;
  /** A tap on an open gift: replays its effect, or a queued gift that failed: its options. */
  onPress?: () => void;
  /** What a tap does, for screen readers. */
  hint?: string;
  onLongPress?: () => void;
  testID: string;
}

const SIZE = 132;

/**
 * A gift in the chat (DM-016). The recipient gets it wrapped, gently moving, and opens it with a
 * tap; it then pops open (the chat plays its effect). The sender sees the gift itself, with the
 * effect they chose, and "Opened" once it has been.
 */
export function GiftBubble({
  gift,
  mine,
  senderName,
  onOpen,
  opening = false,
  onPress,
  hint,
  onLongPress,
  testID,
}: GiftBubbleProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const reduceMotion = useReduceMotion();
  const wrapped = !mine && gift.opened_at === null;
  const name = t(giftNameKey(gift.code));
  const [wiggle] = useState(() => new Animated.Value(0));
  const [pop] = useState(() => new Animated.Value(1));
  const [unwrapping, setUnwrapping] = useState(false);

  // The wrapped box nudges now and then so it reads as "open me".
  useEffect(() => {
    if (!wrapped || reduceMotion) return;
    const nudge = (toValue: number) =>
      Animated.timing(wiggle, { toValue, duration: 90, useNativeDriver: true });
    const loop = Animated.loop(
      Animated.sequence([nudge(1), nudge(-1), nudge(1), nudge(0), Animated.delay(1800)]),
    );
    loop.start();
    return () => loop.stop();
  }, [wrapped, reduceMotion, wiggle]);

  // Once it is open after a tap here, the gift springs out of the box.
  useEffect(() => {
    if (!unwrapping || wrapped || reduceMotion) return;
    pop.setValue(0.35);
    Animated.spring(pop, { toValue: 1, friction: 4, tension: 140, useNativeDriver: true }).start();
  }, [unwrapping, wrapped, reduceMotion, pop]);

  const rotate = wiggle.interpolate({ inputRange: [-1, 1], outputRange: ['-6deg', '6deg'] });
  const align = mine ? styles.mine : styles.theirs;

  if (wrapped) {
    return (
      <Pressable
        onPress={() => {
          setUnwrapping(true);
          onOpen?.();
        }}
        onLongPress={onLongPress}
        disabled={opening}
        accessibilityRole="button"
        accessibilityLabel={t('messages.giftWrappedA11y', { name: senderName })}
        accessibilityState={{ busy: opening }}
        style={[styles.column, align]}
        testID={testID}
      >
        <Animated.Image
          source={WRAPPED_GIFT}
          style={[styles.image, { transform: [{ rotate }] }]}
          resizeMode="contain"
          accessibilityIgnoresInvertColors
        />
        {/* On a pill so it reads over a chat background photo. */}
        <Text
          style={[
            theme.typography.caption,
            styles.from,
            { color: theme.colors.textPrimary, backgroundColor: theme.colors.surface },
          ]}
        >
          {t('messages.giftFrom', { name: senderName })}
        </Text>
        <View style={[styles.pill, { backgroundColor: theme.colors.primary }]}>
          {opening ? (
            <ActivityIndicator size="small" color={theme.colors.onPrimary} />
          ) : (
            <Ionicons name="gift-outline" size={14} color={theme.colors.onPrimary} />
          )}
          <Text style={[theme.typography.label, { color: theme.colors.onPrimary }]}>
            {t('messages.giftTapToOpen')}
          </Text>
        </View>
      </Pressable>
    );
  }

  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      accessibilityRole={onPress ? 'button' : 'image'}
      accessibilityHint={hint}
      accessibilityLabel={
        mine
          ? t('messages.giftSentA11y', { gift: name })
          : t('messages.giftOpenedA11y', { gift: name })
      }
      style={[styles.column, align]}
      testID={testID}
    >
      <Animated.Image
        source={giftImage(gift.code)}
        style={[styles.image, { transform: [{ scale: pop }] }]}
        resizeMode="contain"
        accessibilityIgnoresInvertColors
      />
      <View style={[styles.caption, { backgroundColor: theme.colors.surface }]}>
        <Ionicons name="gift" size={13} color={theme.colors.primary} />
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>{name}</Text>
        <Text style={styles.effect}>{GIFT_EFFECT_ICONS[giftEffectOf(gift.effect)]}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  column: { alignItems: 'center', gap: 6, paddingVertical: 4 },
  mine: { alignSelf: 'flex-end' },
  theirs: { alignSelf: 'flex-start' },
  image: { width: SIZE, height: SIZE },
  from: { borderRadius: 10, overflow: 'hidden', paddingHorizontal: 8, paddingVertical: 2 },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 14,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  caption: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  effect: { fontSize: 13 },
});
