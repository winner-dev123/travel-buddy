import { useQuery } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import {
  accountKeys,
  type Entitlements,
  fetchEntitlements,
  type QuotaKey,
} from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

const QUOTAS = {
  'ai.itinerary_generations': 'subscription.quota.ai_itinerary_generations',
  'ai.trip_replans': 'subscription.quota.ai_trip_replans',
  'offline.packages': 'subscription.quota.offline_packages',
  'groups.owned': 'subscription.quota.groups_owned',
} as const satisfies Record<QuotaKey, string>;

/** Where each store lets people change or cancel a subscription (store rules: the app never
 * cancels on its own). Stripe subscriptions are managed on the website. */
function managementUrl(
  management: NonNullable<Entitlements['active_subscription']>['management'],
): string | null {
  if (management === 'app_store') return 'https://apps.apple.com/account/subscriptions';
  if (management === 'google_play') {
    const pkg = Constants.expoConfig?.android?.package ?? 'com.travelbuddy.app';
    return `https://play.google.com/store/account/subscriptions?package=${encodeURIComponent(pkg)}`;
  }
  return null;
}

/** SCR-111 Subscription: plan, renewal, store grace and quota use, with the store's own
 * management page (BILL-004, docs/07). Read-only: purchases happen on the paywall. */
export default function SubscriptionScreen() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const entitlements = useQuery({
    queryKey: accountKeys.entitlements,
    queryFn: () => fetchEntitlements(getApiClient()),
  });
  const day = (iso: string) => new Date(iso).toLocaleDateString(i18n.language);
  const data = entitlements.data;
  const subscription = data?.active_subscription ?? null;
  const manage = subscription ? managementUrl(subscription.management) : null;

  let summary: string | null = null;
  if (data?.plan === 'premium' && data.premium_until) {
    summary = subscription
      ? subscription.auto_renew
        ? t('subscription.renews', { date: day(data.premium_until) })
        : t('subscription.ends', { date: day(data.premium_until) })
      : t('subscription.promotion', { date: day(data.premium_until) });
  } else if (data?.plan === 'premium') {
    summary = t('subscription.noEnd');
  }

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('subscription.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {entitlements.isPending ? <ActivityIndicator /> : null}
        {entitlements.isError ? (
          <Notice tone="error" testID="subscription-error">
            {t('subscription.error')}
          </Notice>
        ) : null}
        {data ? (
          <>
            <Text
              style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
              testID="subscription-plan"
            >
              {t(`subscription.plan.${data.plan}`)}
            </Text>
            {summary ? (
              <Text
                style={[theme.typography.body, { color: theme.colors.textPrimary }]}
                testID="subscription-summary"
              >
                {summary}
              </Text>
            ) : null}
            {data.status === 'in_grace_period' || data.status === 'in_billing_retry' ? (
              <Notice tone="error" testID="subscription-billing-issue">
                {data.store_grace_until
                  ? t('subscription.billingIssueUntil', { date: day(data.store_grace_until) })
                  : t('subscription.billingIssue')}
              </Notice>
            ) : null}
            {data.plan === 'free' && (data.status === 'expired' || data.status === 'revoked') ? (
              <Notice tone="info" testID="subscription-ended">
                {t(`subscription.status.${data.status}`)}
              </Notice>
            ) : null}
            {manage ? (
              <Button
                label={t('subscription.manage')}
                variant="secondary"
                onPress={() => void Linking.openURL(manage).catch(() => undefined)}
                testID="subscription-manage"
              />
            ) : null}
            {subscription?.management === 'stripe_portal' ? (
              <Text
                style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                testID="subscription-web"
              >
                {t('subscription.manageOnWeb')}
              </Text>
            ) : null}
            {data.plan === 'free' ? (
              <Button
                label={t('paywall.getPremium')}
                icon="diamond-outline"
                onPress={() => router.push('/paywall')}
                testID="subscription-get-premium"
              />
            ) : null}
            <Button
              label={t('purchases.title')}
              variant="secondary"
              icon="receipt-outline"
              onPress={() => router.push('/settings/purchases')}
              testID="subscription-history"
            />
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('subscription.usage')}
            </Text>
            {(Object.keys(QUOTAS) as QuotaKey[]).map((key) => {
              const quota = data.quotas[key];
              return (
                <View
                  key={key}
                  style={[styles.quota, { borderColor: theme.colors.divider }]}
                  testID={`quota-${key}`}
                >
                  <Text
                    style={[
                      theme.typography.body,
                      styles.fill,
                      { color: theme.colors.textPrimary },
                    ]}
                  >
                    {t(QUOTAS[key])}
                  </Text>
                  <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                    {quota.limit === 0
                      ? t('subscription.notIncluded')
                      : t('subscription.used', { used: quota.used, limit: quota.limit })}
                  </Text>
                </View>
              );
            })}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  quota: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderBottomWidth: 1,
    paddingVertical: 10,
  },
});
