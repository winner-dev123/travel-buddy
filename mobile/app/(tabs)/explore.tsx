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
  getDestination,
  listGuides,
  nearbyPlaces,
  searchPlaces,
  type PlaceSummary,
} from '@/features/explore/api';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import { PlaceRow } from '@/features/explore/PlaceRow';
import { getCoarsePosition } from '@/features/feed/location';
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
          </View>
        ) : (
          <Notice tone="info">{t('explore.signInToPlan')}</Notice>
        )}

        {heading(t('explore.places'))}
        <DestinationPicker
          value={destination}
          onChange={(value) => {
            setDestination(value);
            setNear(null);
            setQ('');
          }}
          testID="explore-destination"
        />
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
});
