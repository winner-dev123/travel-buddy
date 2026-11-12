import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';

import { Button } from '@/components/Form';
import { useAppTheme } from '@/theme/useAppTheme';

import {
  DEFAULT_GIFT_EFFECT,
  GIFT_CODES,
  GIFT_EFFECT_ICONS,
  GIFT_EFFECTS,
  giftEffectNameKey,
  giftImage,
  giftNameKey,
  PANEL_EMOJI,
  type GiftCode,
  type GiftEffect,
} from './gifts';

export type TrayTab = 'emoji' | 'gifts';

export interface ExpressionTrayProps {
  /** Adds an emoji to the message being written. */
  onEmoji: (emoji: string) => void;
  /** Sends a gift with its opening effect; null where gifts aren't offered (group chats: DM-016). */
  onGift: ((gift: GiftCode, effect: GiftEffect) => void) | null;
  /** Plays an effect as a preview when the sender picks it. */
  onPreviewEffect?: (effect: GiftEffect) => void;
}

// Tall enough for both rows of gifts above the effect and send row on a small phone.
const TRAY_HEIGHT = 360;
const EMOJI_SIZE = 44;
const GIFT_COLUMNS = 4;
const GIFT_GAP = 10;
const EFFECT_SIZE = 38;

/**
 * The panel beside the message field (SCR-081, DM-016): emoji to add to the text, and gifts. A
 * gift is chosen first and then sent with its own button, so a stray tap never sends one. Once a
 * gift is chosen, the sender picks what plays when it is opened (petals unless they change it),
 * and each pick plays as a preview.
 */
export function ExpressionTray({ onEmoji, onGift, onPreviewEffect }: ExpressionTrayProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState<TrayTab>('emoji');
  const [chosen, setChosen] = useState<GiftCode | null>(null);
  const [effect, setEffect] = useState<GiftEffect>(DEFAULT_GIFT_EFFECT);
  const padding = theme.spacing[3];
  const giftWidth = Math.floor(
    (width - padding * 2 - GIFT_GAP * (GIFT_COLUMNS - 1)) / GIFT_COLUMNS,
  );
  const showing: TrayTab = onGift ? tab : 'emoji';

  const tabButton = (value: TrayTab, label: string) => {
    const selected = showing === value;
    return (
      <Pressable
        key={value}
        onPress={() => setTab(value)}
        accessibilityRole="tab"
        accessibilityState={{ selected }}
        style={[
          styles.tab,
          {
            backgroundColor: selected ? theme.colors.primaryMuted : 'transparent',
            borderColor: selected ? theme.colors.primary : theme.colors.divider,
          },
        ]}
        testID={`tray-tab-${value}`}
      >
        <Text
          style={[
            theme.typography.label,
            { color: selected ? theme.colors.onPrimaryMuted : theme.colors.textSecondary },
          ]}
        >
          {label}
        </Text>
      </Pressable>
    );
  };

  return (
    <View
      style={[styles.tray, { borderTopColor: theme.colors.divider, paddingHorizontal: padding }]}
      testID="expression-tray"
    >
      {onGift ? (
        <View style={styles.tabs} accessibilityRole="tablist">
          {tabButton('emoji', t('messages.emojiTab'))}
          {tabButton('gifts', t('messages.giftsTab'))}
        </View>
      ) : null}
      {showing === 'emoji' ? (
        <ScrollView contentContainerStyle={styles.emojiGrid} keyboardShouldPersistTaps="handled">
          {PANEL_EMOJI.map((emoji) => (
            <Pressable
              key={emoji}
              onPress={() => onEmoji(emoji)}
              accessibilityRole="button"
              accessibilityLabel={emoji}
              style={({ pressed }) => [
                styles.emoji,
                { backgroundColor: pressed ? theme.colors.surfaceRaised : 'transparent' },
              ]}
              testID={`emoji-${emoji}`}
            >
              <Text style={styles.emojiText}>{emoji}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : (
        <View style={styles.fill}>
          <ScrollView contentContainerStyle={[styles.giftGrid, { gap: GIFT_GAP }]}>
            {GIFT_CODES.map((code) => {
              const selected = chosen === code;
              const name = t(giftNameKey(code));
              return (
                <Pressable
                  key={code}
                  onPress={() => setChosen(selected ? null : code)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  accessibilityLabel={name}
                  style={[
                    styles.gift,
                    {
                      width: giftWidth,
                      backgroundColor: selected ? theme.colors.primaryMuted : theme.colors.surface,
                      borderColor: selected ? theme.colors.primary : 'transparent',
                    },
                  ]}
                  testID={`gift-${code}`}
                >
                  <Image
                    source={giftImage(code)}
                    style={{ width: giftWidth - 22, height: giftWidth - 22 }}
                    resizeMode="contain"
                    accessibilityIgnoresInvertColors
                  />
                  <Text
                    numberOfLines={2}
                    style={[
                      theme.typography.caption,
                      styles.giftName,
                      {
                        color: selected ? theme.colors.onPrimaryMuted : theme.colors.textSecondary,
                      },
                    ]}
                  >
                    {name}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
          <View style={styles.sendRow}>
            {chosen ? (
              <View style={[styles.fill, styles.effects]}>
                <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                  {t('messages.giftEffect')}
                </Text>
                <View style={styles.effectRow} accessibilityRole="radiogroup">
                  {GIFT_EFFECTS.map((value) => {
                    const selected = effect === value;
                    return (
                      <Pressable
                        key={value}
                        onPress={() => {
                          setEffect(value);
                          onPreviewEffect?.(value);
                        }}
                        accessibilityRole="radio"
                        accessibilityState={{ selected }}
                        accessibilityLabel={t(giftEffectNameKey(value))}
                        accessibilityHint={t('messages.giftEffectHint')}
                        style={[
                          styles.effect,
                          {
                            backgroundColor: selected
                              ? theme.colors.primaryMuted
                              : theme.colors.surface,
                            borderColor: selected ? theme.colors.primary : theme.colors.divider,
                          },
                        ]}
                        testID={`effect-${value}`}
                      >
                        <Text style={styles.effectIcon}>{GIFT_EFFECT_ICONS[value]}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : (
              <Text
                style={[
                  styles.fill,
                  theme.typography.caption,
                  { color: theme.colors.textSecondary },
                ]}
              >
                {t('messages.giftHint')}
              </Text>
            )}
            <Button
              label={chosen ? t('messages.sendGift') : t('messages.chooseGift')}
              onPress={() => {
                if (!chosen || !onGift) return;
                onGift(chosen, effect);
                setChosen(null);
              }}
              disabled={!chosen}
              icon="gift-outline"
              testID="gift-send"
            />
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  tray: { height: TRAY_HEIGHT, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10 },
  tabs: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  tab: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 6 },
  emojiGrid: { flexDirection: 'row', flexWrap: 'wrap', paddingBottom: 12 },
  emoji: {
    width: EMOJI_SIZE,
    height: EMOJI_SIZE,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emojiText: { fontSize: 26 },
  giftGrid: { flexDirection: 'row', flexWrap: 'wrap', paddingBottom: 8 },
  gift: { borderWidth: 1.5, borderRadius: 14, alignItems: 'center', padding: 6, gap: 2 },
  giftName: { textAlign: 'center' },
  sendRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  effects: { gap: 4 },
  effectRow: { flexDirection: 'row', gap: 6 },
  effect: {
    width: EFFECT_SIZE,
    height: EFFECT_SIZE,
    borderRadius: EFFECT_SIZE / 2,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  effectIcon: { fontSize: 19 },
});
