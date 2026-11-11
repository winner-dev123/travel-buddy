import Ionicons from '@expo/vector-icons/Ionicons';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  FlatList,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { accountKeys, fetchTransactions, type BillingTransaction } from '@/features/account/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** An amount in minor units in the reader's locale ("R$ 14,90", "¥1,490"). */
export function formatAmount(minor: number, currency: string, locale: string): string {
  try {
    const format = new Intl.NumberFormat(locale, { style: 'currency', currency });
    const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
    return format.format(minor / 10 ** digits);
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency}`;
  }
}

const PAYMENT_STATUS = {
  pending: 'purchases.status.pending',
  succeeded: 'purchases.status.succeeded',
  failed: 'purchases.status.failed',
} as const;
const DISPUTE_STATUS = {
  open: 'purchases.status.dispute_open',
  won: 'purchases.status.dispute_won',
  lost: 'purchases.status.dispute_lost',
} as const;

function statusKey(item: BillingTransaction) {
  if (item.kind === 'refund') return 'purchases.status.refunded' as const;
  if (item.kind === 'dispute') {
    return DISPUTE_STATUS[item.status as keyof typeof DISPUTE_STATUS] ?? DISPUTE_STATUS.open;
  }
  return PAYMENT_STATUS[item.status as keyof typeof PAYMENT_STATUS] ?? PAYMENT_STATUS.pending;
}

/**
 * SCR-118 Purchase history (BILL-011): payments, refunds and chargebacks across the stores and the
 * website, newest first. Information only: no prices to compare and no link to buy elsewhere.
 */
export default function PurchasesScreen() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const history = useInfiniteQuery({
    queryKey: accountKeys.transactions,
    queryFn: ({ pageParam }) => fetchTransactions(getApiClient(), pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.page.next_cursor ?? undefined,
  });
  const rows = history.data?.pages.flatMap((page) => page.data) ?? [];

  const renderItem = ({ item }: { item: BillingTransaction }) => {
    const title = item.product?.title ?? t(`purchases.kind.${item.kind}`);
    const amount =
      item.amount_minor !== null && item.currency
        ? `${item.kind === 'refund' ? '−' : ''}${formatAmount(
            item.amount_minor,
            item.currency,
            i18n.language,
          )}`
        : null;
    const date = new Date(item.occurred_at).toLocaleDateString(i18n.language, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
    const status = t(statusKey(item));
    const problem = item.status === 'failed' || item.kind !== 'payment';
    return (
      <View
        style={[
          styles.row,
          {
            backgroundColor: theme.colors.surface,
            borderColor: theme.colors.divider,
            borderRadius: theme.radii.lg,
            padding: theme.spacing[3],
            gap: theme.spacing[1],
          },
        ]}
        accessible
        accessibilityLabel={[title, amount ?? t('purchases.amountInStore'), status, date]
          .filter(Boolean)
          .join(', ')}
        testID={`purchase-${item.id}`}
      >
        <View style={styles.line}>
          <Text
            style={[theme.typography.bodyStrong, styles.fill, { color: theme.colors.textPrimary }]}
            numberOfLines={1}
          >
            {title}
          </Text>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {amount ?? '—'}
          </Text>
        </View>
        <View style={styles.line}>
          <Text
            style={[theme.typography.caption, styles.fill, { color: theme.colors.textSecondary }]}
          >
            {date} · {t(`purchases.provider.${item.provider}`)}
          </Text>
          <Text
            style={[
              theme.typography.caption,
              { color: problem ? theme.colors.danger : theme.colors.primary },
            ]}
            testID={`purchase-status-${item.id}`}
          >
            {status}
          </Text>
        </View>
        {amount === null ? (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('purchases.amountInStore')}
          </Text>
        ) : null}
        {item.receipt_url ? (
          <Pressable
            onPress={() => void Linking.openURL(item.receipt_url ?? '').catch(() => undefined)}
            accessibilityRole="link"
            style={[styles.receipt, { minHeight: theme.minTouchTarget }]}
            testID={`purchase-receipt-${item.id}`}
          >
            <Ionicons
              name="document-text-outline"
              size={16}
              color={theme.colors.primary}
              accessible={false}
            />
            <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
              {t('purchases.receipt')}
            </Text>
          </Pressable>
        ) : null}
      </View>
    );
  };

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('purchases.title') }} />
      <FlatList
        testID="purchases-list"
        data={rows}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        onEndReached={() => {
          if (history.hasNextPage && !history.isFetchingNextPage) void history.fetchNextPage();
        }}
        ListEmptyComponent={
          history.isPending ? (
            <ActivityIndicator />
          ) : history.isError ? (
            <Notice tone="error" testID="purchases-error">
              {t('purchases.error')}
            </Notice>
          ) : (
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="purchases-empty"
            >
              {t('purchases.empty')}
            </Text>
          )
        }
        ListFooterComponent={history.isFetchingNextPage ? <ActivityIndicator /> : undefined}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { borderWidth: StyleSheet.hairlineWidth },
  line: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  receipt: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start' },
});
