import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { LinearGradient } from 'expo-linear-gradient';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState, type ComponentProps } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { APP_INFO_KEY, fetchAppInfo } from '@/auth/session';
import { Button, Notice } from '@/components/Form';
import { getPurchaseMode } from '@/config/env';
import { accountKeys, fetchEntitlements, refreshMe } from '@/features/account/api';
import {
  billingKeys,
  buyWithTestStore,
  fetchOffers,
  paywallReason,
  storePlatform,
  type Offer,
} from '@/features/billing/purchases';
import { useAppTheme } from '@/theme/useAppTheme';

type IconName = ComponentProps<typeof Ionicons>['name'];

const REASON_TEXT = {
  'groups.create': 'paywall.reason.groups_create',
  'challenges.create': 'paywall.reason.challenges_create',
  'guides.premium': 'paywall.reason.guides_premium',
  'offline.packages': 'paywall.reason.offline_packages',
  'ai.trip_replan': 'paywall.reason.ai_trip_replan',
  'ai.itinerary_generations': 'paywall.reason.ai_itinerary_generations',
} as const;

const BENEFITS: { icon: IconName; key: 'groups' | 'guides' | 'offline' | 'ai' }[] = [
  { icon: 'people-outline', key: 'groups' },
  { icon: 'book-outline', key: 'guides' },
  { icon: 'cloud-download-outline', key: 'offline' },
  { icon: 'sparkles-outline', key: 'ai' },
];

/**
 * SCR-133 Paywall (BILL-002, BILL-010; ADR-0031): what the traveller tried to do, the Premium
 * benefits and the offers. Purchases go through the App Store or Google Play only: no web prices
 * and no link to buy elsewhere. Until the store adapter ships, release builds show the offers
 * without a buy button; development builds can buy through the backend's test store.
 */
export default function PaywallScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { reason: rawReason } = useLocalSearchParams<{ reason?: string }>();
  const reason = paywallReason(rawReason);
  const mode = getPurchaseMode();
  const key = useRef(getApiClient().newIdempotencyKey());
  const [chosen, setChosen] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);

  const offers = useQuery({
    queryKey: billingKeys.offers(storePlatform()),
    queryFn: () => fetchOffers(getApiClient()),
  });
  const entitlements = useQuery({
    queryKey: accountKeys.entitlements,
    queryFn: () => fetchEntitlements(getApiClient()),
  });
  const info = useQuery({ queryKey: APP_INFO_KEY, queryFn: () => fetchAppInfo(getApiClient()) });
  const list = offers.data ?? [];
  const selected: Offer | undefined = list.find((offer) => offer.id === chosen) ?? list[0];

  const buy = useMutation({
    mutationFn: (offer: Offer) => buyWithTestStore(getApiClient(), offer, key.current),
    onSuccess: (fresh) => {
      queryClient.setQueryData(accountKeys.entitlements, fresh);
      void queryClient.invalidateQueries({ queryKey: accountKeys.transactions });
      void refreshMe(getApiClient()).catch(() => undefined);
    },
  });
  const restore = useMutation({
    mutationFn: () => entitlements.refetch(),
    onSuccess: () => setRestored(true),
  });

  const premium = entitlements.data?.plan === 'premium';
  const store = t(`paywall.store.${storePlatform()}`);
  // Passes say "paid once" in their own description; subscriptions get the renewal line.
  const period = (offer: Offer) =>
    offer.kind === 'auto_renewable' ? t('paywall.period.renews') : '';

  const close = (
    <Pressable
      onPress={() => router.back()}
      accessibilityRole="button"
      accessibilityLabel={t('paywall.close')}
      hitSlop={12}
      style={[styles.close, { backgroundColor: theme.colors.surfaceRaised }]}
      testID="paywall-close"
    >
      <Ionicons name="close" size={20} color={theme.colors.textPrimary} accessible={false} />
    </Pressable>
  );

  if (buy.isSuccess) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <Stack.Screen options={{ headerShown: false }} />
        <View style={[styles.center, { padding: theme.spacing[6], gap: theme.spacing[4] }]}>
          <LinearGradient colors={theme.accentGradient} style={styles.emblem}>
            <Ionicons name="checkmark" size={36} color={theme.colors.onPrimary} />
          </LinearGradient>
          <Text
            accessibilityRole="header"
            style={[theme.typography.title1, styles.centered, { color: theme.colors.textPrimary }]}
            testID="paywall-success"
          >
            {t('paywall.success')}
          </Text>
          <Button label={t('paywall.done')} onPress={() => router.back()} testID="paywall-done" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView
      edges={['top', 'bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[5], gap: theme.spacing[4] }}>
        <View style={styles.top}>{close}</View>
        <View style={[styles.center, { gap: theme.spacing[2] }]}>
          <LinearGradient colors={theme.accentGradient} style={styles.emblem}>
            <Ionicons name="diamond-outline" size={32} color={theme.colors.onPrimary} />
          </LinearGradient>
          <Text style={[theme.typography.overline, styles.upper, { color: theme.colors.primary }]}>
            {t('paywall.overline')}
          </Text>
          <Text
            accessibilityRole="header"
            style={[theme.typography.display, { color: theme.colors.textPrimary }]}
          >
            {t('paywall.title')}
          </Text>
          <Text
            style={[theme.typography.body, styles.centered, { color: theme.colors.textSecondary }]}
            testID="paywall-reason"
          >
            {t(reason ? REASON_TEXT[reason] : 'paywall.reason.default')}
          </Text>
        </View>

        <View
          style={[
            styles.card,
            {
              backgroundColor: theme.colors.surface,
              borderColor: theme.colors.divider,
              borderRadius: theme.radii.lg,
              padding: theme.spacing[4],
              gap: theme.spacing[3],
            },
          ]}
        >
          {BENEFITS.map((benefit) => (
            <View key={benefit.key} style={[styles.benefit, { gap: theme.spacing[3] }]}>
              <View style={[styles.well, { backgroundColor: theme.colors.primaryMuted }]}>
                <Ionicons
                  name={benefit.icon}
                  size={18}
                  color={theme.colors.onPrimaryMuted}
                  accessible={false}
                />
              </View>
              <Text
                style={[theme.typography.body, styles.fill, { color: theme.colors.textPrimary }]}
              >
                {t(`paywall.benefit.${benefit.key}`)}
              </Text>
            </View>
          ))}
        </View>

        {premium ? (
          <View style={{ gap: theme.spacing[3] }}>
            <Notice tone="success" testID="paywall-already">
              {t('paywall.already')}
            </Notice>
            <Button
              label={t('paywall.manage')}
              variant="secondary"
              onPress={() => router.replace('/settings/subscription')}
              testID="paywall-manage"
            />
          </View>
        ) : (
          <View style={{ gap: theme.spacing[3] }}>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('paywall.choose')}
            </Text>
            {offers.isPending ? <ActivityIndicator /> : null}
            {offers.isError ? <Notice tone="error">{t('paywall.offersError')}</Notice> : null}
            {list.map((offer) => {
              const active = offer.id === selected?.id;
              return (
                <Pressable
                  key={offer.id}
                  onPress={() => setChosen(offer.id)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={[offer.title ?? offer.sku, offer.description, period(offer)]
                    .filter(Boolean)
                    .join(', ')}
                  style={[
                    styles.offer,
                    {
                      borderRadius: theme.radii.lg,
                      padding: theme.spacing[4],
                      gap: theme.spacing[1],
                      backgroundColor: active ? theme.colors.surfaceRaised : theme.colors.surface,
                      borderColor: active ? theme.colors.primary : theme.colors.divider,
                      borderWidth: active ? 1.5 : StyleSheet.hairlineWidth,
                    },
                  ]}
                  testID={`paywall-offer-${offer.sku}`}
                >
                  <View style={styles.offerHead}>
                    <Text
                      style={[
                        theme.typography.title3,
                        styles.fill,
                        { color: theme.colors.textPrimary },
                      ]}
                    >
                      {offer.title ?? offer.sku}
                    </Text>
                    <Ionicons
                      name={active ? 'radio-button-on' : 'radio-button-off'}
                      size={22}
                      color={active ? theme.colors.primary : theme.colors.textSecondary}
                      accessible={false}
                    />
                  </View>
                  {offer.description ? (
                    <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                      {offer.description}
                    </Text>
                  ) : null}
                  {period(offer) ? (
                    <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>
                      {period(offer)}
                    </Text>
                  ) : null}
                </Pressable>
              );
            })}
            {mode === 'test' ? (
              <>
                <Text
                  style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                  testID="paywall-test-note"
                >
                  {t('paywall.testNote')}
                </Text>
                <Button
                  label={t('paywall.buyTest')}
                  icon="diamond-outline"
                  onPress={() => selected && buy.mutate(selected)}
                  disabled={!selected}
                  busy={buy.isPending}
                  testID="paywall-buy"
                />
                <Button
                  label={t('paywall.restore')}
                  variant="ghost"
                  onPress={() => restore.mutate()}
                  busy={restore.isPending}
                  testID="paywall-restore"
                />
              </>
            ) : (
              <>
                <Button
                  label={t('paywall.buy')}
                  onPress={() => undefined}
                  disabled
                  testID="paywall-buy"
                />
                <Notice tone="info" testID="paywall-soon">
                  {t('paywall.soon')}
                </Notice>
              </>
            )}
            {buy.isError ? (
              <Notice tone="error" testID="paywall-failed">
                {t('paywall.failed')}
              </Notice>
            ) : null}
            {restored ? <Notice tone="success">{t('paywall.restored')}</Notice> : null}
          </View>
        )}

        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          testID="paywall-disclosure"
        >
          {t('paywall.disclosure', { store })}
        </Text>
        {info.data ? (
          <View style={[styles.links, { gap: theme.spacing[4] }]}>
            <Pressable
              onPress={() => void Linking.openURL(info.data.legal.terms_url).catch(() => undefined)}
              accessibilityRole="link"
              style={styles.link}
              testID="paywall-terms"
            >
              <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                {t('paywall.terms')}
              </Text>
            </Pressable>
            <Pressable
              onPress={() =>
                void Linking.openURL(info.data.legal.privacy_url).catch(() => undefined)
              }
              accessibilityRole="link"
              style={styles.link}
              testID="paywall-privacy"
            >
              <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                {t('paywall.privacy')}
              </Text>
            </Pressable>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { alignItems: 'center' },
  centered: { textAlign: 'center' },
  upper: { textTransform: 'uppercase' },
  top: { alignItems: 'flex-end' },
  close: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emblem: {
    width: 72,
    height: 72,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: { borderWidth: StyleSheet.hairlineWidth },
  benefit: { flexDirection: 'row', alignItems: 'center' },
  well: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  offer: {},
  offerHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  links: { flexDirection: 'row', justifyContent: 'center' },
  link: { minHeight: 44, justifyContent: 'center' },
});
