import { useQuery } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { challengeKeys, listMyRewards } from '@/features/challenges/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-088 My rewards (BL-5.08; CHAL-015): real-world rewards I won and where they stand.
 * A discount code shows here only, to me, once it is issued. */
export default function RewardsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const rewards = useQuery({
    queryKey: challengeKeys.rewards,
    queryFn: () => listMyRewards(getApiClient()),
  });
  const data = rewards.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('challenges.myRewards') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {rewards.isPending ? <ActivityIndicator color={theme.colors.primary} /> : null}
        {rewards.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        {rewards.isSuccess && data.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('challenges.noRewards')}
          </Text>
        ) : null}
        {data.map((item) => (
          <View
            key={item.fulfillment_id}
            style={[styles.card, { borderColor: theme.colors.divider, gap: theme.spacing[1] }]}
            testID={`reward-${item.fulfillment_id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {item.reward.title}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {item.challenge.title} · {t(`challenges.fulfillment.${item.status}`)}
            </Text>
            {item.reward.sponsor_name ? (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('challenges.sponsor', { name: item.reward.sponsor_name })}
              </Text>
            ) : null}
            {item.secret ? (
              <Text
                selectable
                accessibilityLabel={t('challenges.code')}
                style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                testID={`reward-code-${item.fulfillment_id}`}
              >
                {item.secret}
              </Text>
            ) : null}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12 },
});
