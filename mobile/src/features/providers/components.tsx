import Ionicons from '@expo/vector-icons/Ionicons';
import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Avatar } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

import type { Inquiry, ProviderSummary } from './api';
import { requestDates, responseHours } from './format';

/** The provider's logo (or initial) in the shared avatar style. */
export function ProviderLogo({
  provider,
  size = 48,
}: {
  provider: ProviderSummary;
  size?: number;
}) {
  return (
    <Avatar
      user={{
        id: provider.id,
        handle: provider.slug,
        display_name: provider.display_name,
        avatar: provider.logo,
      }}
      size={size}
    />
  );
}

/** "★ 4.8 (12)" or "New", read out in full for screen readers. */
export function Rating({ average, count }: { average: number | null; count: number }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  if (average === null || count === 0) {
    return (
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {t('providers.new')}
      </Text>
    );
  }
  return (
    <View
      style={styles.row}
      accessible
      accessibilityLabel={t('providers.ratingA11y', { rating: average.toFixed(1), count })}
    >
      <Ionicons name="star" size={13} color={theme.colors.primary} accessible={false} />
      <Text style={[theme.typography.caption, { color: theme.colors.textPrimary }]}>
        {average.toFixed(1)}
      </Text>
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        ({count})
      </Text>
    </View>
  );
}

export function VerifiedBadge() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  return (
    <View style={styles.row} testID="provider-verified">
      <Ionicons name="shield-checkmark" size={14} color={theme.colors.primary} accessible={false} />
      <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>
        {t('providers.verified')}
      </Text>
    </View>
  );
}

/** A provider in a list: logo, name, kind and town, rating, reply time. */
export function ProviderCard({
  provider,
  onPress,
}: {
  provider: ProviderSummary;
  onPress: () => void;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const where = provider.base_destination?.name;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={provider.display_name}
      style={({ pressed }) => [
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.divider,
          borderRadius: theme.radii.md,
          padding: theme.spacing[3],
          gap: theme.spacing[3],
          opacity: pressed ? 0.85 : 1,
        },
      ]}
      testID={`provider-${provider.id}`}
    >
      <ProviderLogo provider={provider} />
      <View style={[styles.fill, { gap: 2 }]}>
        <Text
          style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}
          numberOfLines={1}
        >
          {provider.display_name}
        </Text>
        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          numberOfLines={1}
        >
          {[t(`providers.kind.${provider.kind}`), where].filter(Boolean).join(' · ')}
        </Text>
        {provider.tagline ? (
          <Text
            style={[theme.typography.caption, { color: theme.colors.textPrimary }]}
            numberOfLines={2}
          >
            {provider.tagline}
          </Text>
        ) : null}
        <View style={[styles.row, { gap: theme.spacing[3] }]}>
          <Rating average={provider.rating_average} count={provider.rating_count} />
          {provider.response_time_seconds !== null ? (
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('providers.repliesWithin', {
                count: responseHours(provider.response_time_seconds),
              })}
            </Text>
          ) : null}
        </View>
      </View>
      <Ionicons
        name="chevron-forward"
        size={18}
        color={theme.colors.textSecondary}
        accessible={false}
      />
    </Pressable>
  );
}

/** A request's essentials: status, offering, dates, party size. */
export function RequestCard({
  inquiry,
  onPress,
  showProvider = true,
}: {
  inquiry: Inquiry;
  onPress?: () => void;
  showProvider?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const dates = requestDates(inquiry, i18n.language);
  const who =
    inquiry.viewer_side === 'provider'
      ? (inquiry.traveler?.display_name ?? t('providers.formerTraveler'))
      : inquiry.provider.display_name;
  const body = (
    <View style={{ gap: theme.spacing[1] }}>
      <View style={[styles.row, { justifyContent: 'space-between' }]}>
        {showProvider ? (
          <Text
            style={[styles.fill, theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}
            numberOfLines={1}
          >
            {who}
          </Text>
        ) : (
          <Text
            style={[styles.fill, theme.typography.label, { color: theme.colors.textSecondary }]}
          >
            {t('providers.request.cardTitle')}
          </Text>
        )}
        <StatusPill status={inquiry.status} />
      </View>
      {inquiry.offering ? (
        <Text style={[theme.typography.caption, { color: theme.colors.textPrimary }]}>
          {inquiry.offering.title}
        </Text>
      ) : null}
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {[
          dates ?? t('providers.request.flexible'),
          t('providers.request.people', { count: inquiry.party_size }),
        ].join(' · ')}
      </Text>
    </View>
  );
  const frame = {
    backgroundColor: theme.colors.surface,
    borderColor: theme.colors.divider,
    borderRadius: theme.radii.md,
    padding: theme.spacing[3],
  };
  if (!onPress) {
    return <View style={[styles.box, frame]}>{body}</View>;
  }
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={({ pressed }) => [styles.box, frame, { opacity: pressed ? 0.85 : 1 }]}
      testID={`request-${inquiry.id}`}
    >
      {body}
    </Pressable>
  );
}

export function StatusPill({ status }: { status: Inquiry['status'] }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const good = status === 'accepted' || status === 'completed';
  const waiting = status === 'open';
  return (
    <View
      style={[
        styles.pill,
        {
          backgroundColor: good
            ? theme.colors.successSurface
            : waiting
              ? theme.colors.infoSurface
              : theme.colors.surfaceRaised,
          borderRadius: theme.radii.pill,
        },
      ]}
    >
      <Text
        style={[
          theme.typography.caption,
          {
            color: good
              ? theme.colors.onSuccessSurface
              : waiting
                ? theme.colors.onInfoSurface
                : theme.colors.textSecondary,
          },
        ]}
      >
        {t(`providers.status.${status}`)}
      </Text>
    </View>
  );
}

/** In-person safety tips shown before a first request (PROV-009). */
export function SafetyTips() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const tips = ['public', 'share', 'pay', 'report'] as const;
  return (
    <View
      style={[
        styles.box,
        {
          backgroundColor: theme.colors.infoSurface,
          borderRadius: theme.radii.md,
          padding: theme.spacing[3],
          gap: theme.spacing[1],
        },
      ]}
      testID="provider-safety-tips"
    >
      <Text style={[theme.typography.label, { color: theme.colors.onInfoSurface }]}>
        {t('providers.safety.title')}
      </Text>
      {tips.map((tip) => (
        <Text key={tip} style={[theme.typography.caption, { color: theme.colors.onInfoSurface }]}>
          {`• ${t(`providers.safety.${tip}`)}`}
        </Text>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  card: { flexDirection: 'row', alignItems: 'center', borderWidth: StyleSheet.hairlineWidth },
  box: { borderWidth: StyleSheet.hairlineWidth },
  pill: { paddingHorizontal: 10, paddingVertical: 2 },
});
