import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Alert, Image, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { showActions } from '@/components/ActionSheet';
import { Chip } from '@/components/Chip';
import { Button, Notice } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import {
  blockProvider,
  getProvider,
  listOfferings,
  listReviews,
  providerKeys,
  type Offering,
} from '@/features/providers/api';
import { ProviderLogo, Rating, VerifiedBadge } from '@/features/providers/components';
import { durationParts, formatPrice, responseHours } from '@/features/providers/format';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-161 A guide's or company's public profile: offerings, reviews, request (PROV-002/007). */
export default function ProviderScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <ProviderProfileView />
    </ServerFeature>
  );
}

function ProviderProfileView() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const profile = useQuery({
    queryKey: providerKeys.profile(id),
    queryFn: () => getProvider(getApiClient(), id),
  });
  const offerings = useQuery({
    queryKey: providerKeys.offerings(id, false),
    queryFn: () => listOfferings(getApiClient(), id),
  });
  const reviews = useQuery({
    queryKey: providerKeys.reviews(id),
    queryFn: () => listReviews(getApiClient(), id),
  });
  const block = useMutation({
    mutationFn: () => blockProvider(getApiClient(), id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: providerKeys.all });
      router.back();
    },
  });
  const data = profile.data;
  const member = data?.membership?.status === 'active';

  const more = () =>
    showActions(data?.display_name ?? '', undefined, [
      {
        text: t('providers.report'),
        onPress: () =>
          router.push({
            pathname: '/report',
            params: { type: 'provider', target: id, name: data?.display_name ?? '' },
          }),
      },
      {
        text: t('providers.block'),
        style: 'destructive',
        onPress: () =>
          Alert.alert(t('providers.blockTitle'), t('providers.blockBody'), [
            { text: t('common.cancel'), style: 'cancel' },
            { text: t('providers.block'), style: 'destructive', onPress: () => block.mutate() },
          ]),
      },
      { text: t('common.cancel'), style: 'cancel' },
    ]);

  const offeringRow = (offering: Offering) => {
    const duration = offering.duration_minutes ? durationParts(offering.duration_minutes) : null;
    return (
      <Pressable
        key={offering.id}
        onPress={() =>
          router.push({ pathname: '/providers/offering/[id]', params: { id: offering.id } })
        }
        accessibilityRole="button"
        style={[
          styles.row,
          { borderColor: theme.colors.divider, paddingVertical: theme.spacing[2] },
        ]}
        testID={`offering-${offering.id}`}
      >
        <View style={[styles.fill, { gap: 2 }]}>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {offering.title}
          </Text>
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {[
              t(`providers.offeringKind.${offering.kind}`),
              duration
                ? duration.days
                  ? t('providers.days', { count: duration.days })
                  : t('providers.duration', { hours: duration.hours, minutes: duration.mins })
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </View>
        {offering.price_from ? (
          <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
            {t('providers.from', { price: formatPrice(offering.price_from, i18n.language) })}
          </Text>
        ) : null}
      </Pressable>
    );
  };

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: data?.display_name ?? t('providers.title'),
          headerRight: () =>
            data && signedIn && !member ? (
              <Pressable
                onPress={more}
                accessibilityRole="button"
                accessibilityLabel={t('providers.more')}
                hitSlop={10}
                testID="provider-more"
              >
                <Ionicons name="ellipsis-horizontal" size={22} color={theme.colors.textPrimary} />
              </Pressable>
            ) : null,
        }}
      />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {profile.isError ? <Notice tone="error">{t('providers.missing')}</Notice> : null}
        {data ? (
          <>
            {data.cover?.status === 'ready' && data.cover.url ? (
              <Image
                source={{ uri: data.cover.url }}
                style={[styles.cover, { borderRadius: theme.radii.md }]}
                accessibilityIgnoresInvertColors
              />
            ) : null}
            <View style={[styles.head, { gap: theme.spacing[3] }]}>
              <ProviderLogo provider={data} size={64} />
              <View style={[styles.fill, { gap: 2 }]}>
                <Text
                  accessibilityRole="header"
                  style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
                >
                  {data.display_name}
                </Text>
                <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                  {[t(`providers.kind.${data.kind}`), data.base_destination?.name]
                    .filter(Boolean)
                    .join(' · ')}
                </Text>
                <Rating average={data.rating_average} count={data.rating_count} />
              </View>
            </View>
            {data.verified_at ? <VerifiedBadge /> : null}
            {data.tagline ? (
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {data.tagline}
              </Text>
            ) : null}
            {data.response_time_seconds !== null ? (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('providers.repliesWithin', { count: responseHours(data.response_time_seconds) })}
              </Text>
            ) : null}
            {member ? (
              <Button
                label={t('providers.workspace.open')}
                variant="secondary"
                onPress={() =>
                  router.push({ pathname: '/providers/workspace/[id]', params: { id } })
                }
                testID="provider-open-workspace"
              />
            ) : signedIn ? (
              <Button
                label={t('providers.request.send')}
                icon="chatbubbles-outline"
                onPress={() =>
                  router.push({ pathname: '/providers/request', params: { providerId: id } })
                }
                testID="provider-request"
              />
            ) : (
              <Notice tone="info">{t('providers.signInToRequest')}</Notice>
            )}
            {data.about ? (
              <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                {data.about}
              </Text>
            ) : null}
            <View style={styles.chips}>
              {data.specialties.map((s) => (
                <Chip key={s} label={t(`providers.specialty.${s}`)} onPress={() => undefined} />
              ))}
            </View>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('providers.languages', {
                languages: data.languages
                  .map((code) => languageName(code, i18n.language))
                  .join(', '),
              })}
            </Text>
            {data.service_areas.length > 0 ? (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('providers.alsoServes', {
                  places: data.service_areas.map((a) => a.name).join(', '),
                })}
              </Text>
            ) : null}
            {data.years_experience ? (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('providers.experience', { count: data.years_experience })}
              </Text>
            ) : null}
            {data.website_url ? (
              <Pressable
                onPress={() => void Linking.openURL(data.website_url as string)}
                accessibilityRole="link"
              >
                <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                  {data.website_url}
                </Text>
              </Pressable>
            ) : null}

            <Text
              accessibilityRole="header"
              style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
            >
              {t('providers.offerings')}
            </Text>
            {(offerings.data?.data ?? []).length === 0 ? (
              <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                {t('providers.noOfferings')}
              </Text>
            ) : null}
            {(offerings.data?.data ?? []).map(offeringRow)}
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('providers.priceNote')}
            </Text>

            <Text
              accessibilityRole="header"
              style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
            >
              {t('providers.reviews')}
            </Text>
            {(reviews.data?.data ?? []).length === 0 ? (
              <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                {t('providers.noReviews')}
              </Text>
            ) : null}
            {(reviews.data?.data ?? []).map((review) => (
              <View
                key={review.id}
                style={[styles.review, { borderColor: theme.colors.divider, gap: 4 }]}
                testID={`review-${review.id}`}
              >
                <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                  {`${'★'.repeat(review.rating)}${'☆'.repeat(5 - review.rating)}  ${
                    review.author?.display_name ?? t('providers.formerTraveler')
                  }`}
                </Text>
                {review.body ? (
                  <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                    {review.body}
                  </Text>
                ) : null}
                {review.reply ? (
                  <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                    {t('providers.reply', { name: data.display_name, body: review.reply.body })}
                  </Text>
                ) : null}
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function languageName(code: string, locale: string): string {
  try {
    const names = new Intl.DisplayNames([locale], { type: 'language' });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  head: { flexDirection: 'row', alignItems: 'center' },
  cover: { width: '100%', aspectRatio: 16 / 9 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  review: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 8 },
});
