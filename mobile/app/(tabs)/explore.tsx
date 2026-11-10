import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { FeatureGate } from '@/components/FeatureGate';
import { Button, Notice, TextField } from '@/components/Form';
import {
  exploreKeys,
  destinationChildren,
  featuredDestinations,
  getDestination,
  listGuides,
  nearbyPlaces,
  searchPlaces,
  type PlaceSummary,
} from '@/features/explore/api';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import { PlaceRow } from '@/features/explore/PlaceRow';
import { getCoarsePosition } from '@/features/feed/location';
import { OfflinePackages } from '@/features/offline/OfflinePackages';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-040 Explore: places in a destination or near me, and the AI planner entry (Phase 4). */
export default function ExploreScreen() {
  return (
    <FeatureGate feature="explore">
      <Explore />
    </FeatureGate>
  );
}

function Explore() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const [destination, setDestination] = useState<DestinationSummary | null>(null);
  const [near, setNear] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [locationDenied, setLocationDenied] = useState(false);
  const [q, setQ] = useState('');

  const detail = useQuery({
    queryKey: exploreKeys.destination(destination?.id ?? ''),
    queryFn: () => getDestination(getApiClient(), destination!.id),
    enabled: destination !== null,
  });
  const featured = useQuery({
    queryKey: ['destinations', 'featured'],
    queryFn: () => featuredDestinations(getApiClient()),
    enabled: destination === null,
    staleTime: 10 * 60 * 1000,
  });
  const children = useQuery({
    queryKey: ['destinations', 'children', destination?.id ?? ''],
    queryFn: () => destinationChildren(getApiClient(), destination!.id),
    enabled: destination !== null && destination.kind === 'city',
    staleTime: 10 * 60 * 1000,
  });
  const choose = (value: DestinationSummary | null) => {
    setDestination(value);
    setNear(null);
    setQ('');
  };
  const chip = [styles.chip, { borderColor: theme.colors.divider }];
  const guides = useQuery({
    queryKey: ['guides', 'destination', destination?.id ?? ''],
    queryFn: () => listGuides(getApiClient(), destination!.id),
    enabled: destination !== null,
  });
  const point =
    near ??
    (detail.data
      ? `${detail.data.centroid.lat.toFixed(3)},${detail.data.centroid.lng.toFixed(3)}`
      : null);
  const term = q.trim();
  const places = useQuery({
    queryKey:
      term.length >= 2 && destination
        ? exploreKeys.search(destination.id, term)
        : exploreKeys.nearby(point ?? ''),
    queryFn: (): Promise<PlaceSummary[]> =>
      term.length >= 2 && destination
        ? searchPlaces(getApiClient(), destination.id, term)
        : nearbyPlaces(getApiClient(), point!),
    enabled: signedIn && ((term.length >= 2 && destination !== null) || point !== null),
  });

  const locate = async () => {
    setLocating(true);
    const position = await getCoarsePosition();
    setLocating(false);
    if (position.status === 'granted') {
      setLocationDenied(false);
      setDestination(null);
      setQ('');
      setNear(position.near);
    } else {
      setLocationDenied(true);
    }
  };

  const heading = (text: string) => (
    <Text
      accessibilityRole="header"
      style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
    >
      {text}
    </Text>
  );

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text
          accessibilityRole="header"
          style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
        >
          {t('tabs.explore')}
        </Text>
        {signedIn ? (
          <View style={{ gap: theme.spacing[2] }}>
            <Button
              label={t('explore.plan')}
              onPress={() => router.push('/trips/plan')}
              testID="explore-plan"
            />
            <Button
              label={t('explore.myTrips')}
              variant="secondary"
              onPress={() => router.push('/trips')}
              testID="explore-trips"
            />
            <Button
              label={t('offline.downloads')}
              variant="secondary"
              onPress={() => router.push('/downloads')}
              testID="explore-downloads"
            />
          </View>
        ) : (
          <Notice tone="info">{t('explore.signInToPlan')}</Notice>
        )}

        {heading(t('explore.places'))}
        <DestinationPicker value={destination} onChange={choose} testID="explore-destination" />
        {destination === null && (featured.data ?? []).length > 0 ? (
          <View style={styles.chips} testID="explore-featured">
            {(featured.data ?? []).map((item) => (
              <Pressable
                key={item.id}
                onPress={() => choose(item)}
                accessibilityRole="button"
                style={chip}
                testID={`explore-featured-${item.slug}`}
              >
                <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                  {item.name}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        {destination && (children.data ?? []).length > 0 ? (
          <View style={{ gap: theme.spacing[2] }}>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('explore.neighbourhoods', { place: destination.name })}
            </Text>
            <View style={styles.chips} testID="explore-children">
              {(children.data ?? []).map((item) => (
                <Pressable
                  key={item.id}
                  onPress={() => choose(item)}
                  accessibilityRole="button"
                  style={chip}
                  testID={`explore-child-${item.slug}`}
                >
                  <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
                    {item.name}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}
        {(guides.data ?? []).length > 0 ? heading(t('guides.title')) : null}
        {(guides.data ?? []).map((guide) => (
          <Pressable
            key={guide.id}
            onPress={() => router.push({ pathname: '/guides/[id]', params: { id: guide.id } })}
            accessibilityRole="link"
            accessibilityLabel={guide.title}
            style={[styles.row, { borderColor: theme.colors.divider }]}
            testID={`guide-${guide.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {guide.title}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {guide.entitled ? guide.summary : t('guides.premium')}
            </Text>
          </Pressable>
        ))}
        {destination && signedIn ? <OfflinePackages destination={destination} /> : null}
        {destination ? (
          <TextField
            label={t('explore.searchPlaces', { place: destination.name })}
            value={q}
            onChangeText={setQ}
            autoCorrect={false}
            testID="explore-search"
          />
        ) : null}
        <Button
          label={t('explore.nearMe')}
          variant="secondary"
          onPress={() => void locate()}
          busy={locating}
          testID="explore-near-me"
        />
        {locationDenied ? <Notice tone="info">{t('explore.locationDenied')}</Notice> : null}
        {!signedIn ? null : places.isError ? (
          <Notice tone="error">{t('explore.loadFailed')}</Notice>
        ) : places.data && places.data.length === 0 ? (
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('explore.noPlaces')}
          </Text>
        ) : null}
        {(places.data ?? []).map((place) => (
          <PlaceRow
            key={place.id}
            place={place}
            onOpen={() => router.push({ pathname: '/places/[id]', params: { id: place.id } })}
          />
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 10, gap: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 12, paddingVertical: 6 },
});
