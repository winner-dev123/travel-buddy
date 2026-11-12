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

import { GIFT_CODES, giftImage, giftNameKey, PANEL_EMOJI, type GiftCode } from './gifts';

export type TrayTab = 'emoji' | 'gifts';

export interface ExpressionTrayProps {
  /** Adds an emoji to the message being written. */
  onEmoji: (emoji: string) => void;
  /** Sends a gift; null where gifts aren't offered (group chats: DM-016). */
  onGift: ((gift: GiftCode) => void) | null;
}

// Tall enough for both rows of gifts above the send row on a small phone.
const TRAY_HEIGHT = 350;
const EMOJI_SIZE = 44;
const GIFT_COLUMNS = 4;
const GIFT_GAP = 10;

/**
 * The panel beside the message field (SCR-081, DM-016): emoji to add to the text, and gifts. A
 * gift is chosen first and then sent with its own button, so a stray tap never sends one.
 */
export function ExpressionTray({ onEmoji, onGift }: ExpressionTrayProps) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState<TrayTab>('emoji');
  const [chosen, setChosen] = useState<GiftCode | null>(null);
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
            <Text
              style={[styles.fill, theme.typography.caption, { color: theme.colors.textSecondary }]}
            >
              {t('messages.giftHint')}
            </Text>
            <Button
              label={chosen ? t('messages.sendGift') : t('messages.chooseGift')}
              onPress={() => {
                if (!chosen || !onGift) return;
                onGift(chosen);
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
});
