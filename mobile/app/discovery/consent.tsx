import { Stack, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { DiscoverySafetyNotice } from '@/components/DiscoverySafetyNotice';
import { Button, Notice, SwitchRow } from '@/components/Form';
import { refreshMe } from '@/features/account/api';
import { enableDiscovery } from '@/features/discovery/api';
import { useAppTheme } from '@/theme/useAppTheme';

const POINTS = ['shared', 'never', 'expires', 'control'] as const;

/**
 * SCR-061 Discovery consent (DISC-001, DISC-010): what is shared, the safety guidance, an explicit
 * acknowledgement, then the consent is recorded and discovery switched on. Never called "safe".
 */
export default function DiscoveryConsentScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const [granularity, setGranularity] = useState<'city' | 'neighborhood'>('city');
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function turnOn(): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      const client = getApiClient();
      await enableDiscovery(client, granularity);
      await refreshMe(client);
      router.back();
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('discovery.consentTitle') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}>
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {t('discovery.consentIntro')}
        </Text>
        {POINTS.map((point) => (
          <Text key={point} style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
            {`• ${t(`discovery.points.${point}`)}`}
          </Text>
        ))}
        <DiscoverySafetyNotice />
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('discovery.granularity')}
        </Text>
        <View style={styles.row} accessibilityRole="radiogroup">
          {(['city', 'neighborhood'] as const).map((value) => {
            const selected = value === granularity;
            return (
              <Pressable
                key={value}
                onPress={() => setGranularity(value)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                style={[
                  styles.choice,
                  {
                    backgroundColor: selected ? theme.colors.primary : theme.colors.surface,
                    borderColor: selected ? theme.colors.primary : theme.colors.borderStrong,
                  },
                ]}
                testID={`discovery-granularity-${value}`}
              >
                <Text
                  style={[
                    theme.typography.label,
                    { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
                  ]}
                >
                  {t(`discovery.granularities.${value}`)}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <SwitchRow
          label={t('discovery.understand')}
          value={understood}
          onValueChange={setUnderstood}
          testID="discovery-understand"
        />
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button
          label={t('discovery.turnOn')}
          onPress={() => void turnOn()}
          disabled={!understood}
          busy={busy}
          testID="discovery-turn-on"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', gap: 8 },
  choice: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 10,
    minHeight: 44,
  },
});
