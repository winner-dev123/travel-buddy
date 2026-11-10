import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/Form';
import { useAppTheme } from '@/theme/useAppTheme';

const SECTIONS = ['meeting', 'location', 'scams', 'reporting', 'emergency'] as const;

/** SCR-114 Safety center (SAFE-008): guidance for meeting travellers, location, scams, how
 * reporting and blocking work, and emergencies. Bundled with the app, so it works offline. */
export default function SafetyCenterScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('safetyCenter.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[4] }}>
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {t('safetyCenter.intro')}
        </Text>
        {SECTIONS.map((section) => (
          <View key={section} style={{ gap: theme.spacing[2] }} testID={`safety-${section}`}>
            <Text
              accessibilityRole="header"
              style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
            >
              {t(`safetyCenter.${section}.title`)}
            </Text>
            {(t(`safetyCenter.${section}.points`, { returnObjects: true }) as string[]).map(
              (point, index) => (
                <Text
                  key={index}
                  style={[theme.typography.body, { color: theme.colors.textPrimary }]}
                >
                  {`• ${point}`}
                </Text>
              ),
            )}
          </View>
        ))}
        <Button
          label={t('safetyCenter.contact')}
          variant="secondary"
          onPress={() => router.push('/settings/help')}
          testID="safety-contact"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
