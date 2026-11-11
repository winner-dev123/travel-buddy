import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack } from 'expo-router';
import type { ComponentProps } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { type ThemePreference, useSettingsStore } from '@/state/settingsStore';
import { chooseThemePreference } from '@/state/uiPreferences';
import { useAppTheme } from '@/theme/useAppTheme';

type IoniconName = ComponentProps<typeof Ionicons>['name'];

const OPTIONS: { value: ThemePreference; icon: IoniconName }[] = [
  { value: 'dark', icon: 'moon-outline' },
  { value: 'light', icon: 'sunny-outline' },
  { value: 'system', icon: 'phone-portrait-outline' },
];

/** SCR-117 Appearance: dark (the default), light, or follow the device. Kept on the device. */
export default function AppearanceScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const preference = useSettingsStore((state) => state.themePreference);

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('appearance.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel={t('appearance.title')}
          style={[
            styles.card,
            { backgroundColor: theme.colors.surface, borderColor: theme.colors.divider },
          ]}
        >
          {OPTIONS.map(({ value, icon }, index) => {
            const selected = preference === value;
            return (
              <Pressable
                key={value}
                onPress={() => chooseThemePreference(value)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                style={({ pressed }) => [
                  styles.row,
                  {
                    minHeight: theme.minTouchTarget,
                    padding: theme.spacing[4],
                    gap: theme.spacing[3],
                    backgroundColor: pressed ? theme.colors.surfaceRaised : 'transparent',
                    borderTopColor: theme.colors.divider,
                    borderTopWidth: index === 0 ? 0 : StyleSheet.hairlineWidth,
                  },
                ]}
                testID={`appearance-${value}`}
              >
                <View style={[styles.well, { backgroundColor: theme.colors.primaryMuted }]}>
                  <Ionicons name={icon} size={18} color={theme.colors.onPrimaryMuted} />
                </View>
                <View style={styles.text}>
                  <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                    {t(`appearance.options.${value}`)}
                  </Text>
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {t(`appearance.descriptions.${value}`)}
                  </Text>
                </View>
                <Ionicons
                  name={selected ? 'radio-button-on' : 'radio-button-off'}
                  size={22}
                  color={selected ? theme.colors.primary : theme.colors.textSecondary}
                />
              </Pressable>
            );
          })}
        </View>
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('appearance.hint')}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 16, overflow: 'hidden' },
  row: { flexDirection: 'row', alignItems: 'center' },
  well: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: { flex: 1, gap: 2 },
});
