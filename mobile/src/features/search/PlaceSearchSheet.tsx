import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState, type ComponentProps } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { featuredDestinations } from '@/features/explore/api';
import { getCoarsePosition } from '@/features/feed/location';
import { useAppTheme } from '@/theme/useAppTheme';

import {
  resolveDestination,
  searchKeys,
  suggestDestinations,
  suggestionKey,
  whereIs,
  type Suggestion,
} from './api';
import { useRecentSearches } from './recents';

type IoniconName = ComponentProps<typeof Ionicons>['name'];

/** Letters typed before suggestions start, and the pause that counts as "done typing". */
export const MIN_QUERY = 2;
export const DEBOUNCE_MS = 250;

const PLACE_ICONS: Record<string, IoniconName> = {
  attraction: 'star-outline',
  museum: 'library-outline',
  beach: 'umbrella-outline',
  viewpoint: 'eye-outline',
  park: 'leaf-outline',
  trail: 'walk-outline',
  market: 'basket-outline',
};
const DESTINATION_ICONS: Record<string, IoniconName> = {
  country: 'flag-outline',
  city: 'business-outline',
  neighborhood: 'map-outline',
  district: 'map-outline',
  area: 'map-outline',
};

function iconFor(suggestion: Suggestion): IoniconName {
  return suggestion.type === 'place'
    ? (PLACE_ICONS[suggestion.place.category] ?? 'star-outline')
    : (DESTINATION_ICONS[suggestion.destination.kind] ?? 'location-outline');
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

type HereState = 'idle' | 'locating' | 'denied' | 'unavailable' | 'uncovered' | 'failed';

/**
 * Full-screen search for towns and places to visit, like a ride app's "Where to?" (ADR-0035):
 * the current location first, then recent choices and popular destinations; as you type, towns,
 * neighbourhoods, countries and tourist places come back with where they are. No streets or
 * addresses. With `placesAllowed` false only destinations are offered.
 */
export function PlaceSearchSheet({
  visible,
  onClose,
  onSelect,
  testID,
  placesAllowed = true,
  title,
}: {
  visible: boolean;
  onClose: () => void;
  onSelect: (suggestion: Suggestion) => void;
  testID: string;
  placesAllowed?: boolean;
  title?: string;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const [query, setQuery] = useState('');
  const [here, setHere] = useState<HereState>('idle');
  const term = useDebounced(query.trim(), DEBOUNCE_MS);
  const searching = term.length >= MIN_QUERY;
  const recents = useRecentSearches((state) => state.items);
  const loadRecents = useRecentSearches((state) => state.load);
  const remember = useRecentSearches((state) => state.remember);

  useEffect(() => {
    if (visible) loadRecents();
  }, [visible, loadRecents]);

  const results = useQuery({
    queryKey: searchKeys.suggest(term),
    queryFn: () => suggestDestinations(getApiClient(), term),
    enabled: visible && searching,
    staleTime: 5 * 60_000,
    placeholderData: (previous) => previous,
  });
  const popular = useQuery({
    queryKey: ['destinations', 'featured'],
    queryFn: () => featuredDestinations(getApiClient()),
    enabled: visible && !searching,
    staleTime: 10 * 60_000,
  });

  const allowed = (item: Suggestion) => placesAllowed || item.type === 'destination';
  // Every way out starts the next search afresh.
  const close = () => {
    setQuery('');
    setHere('idle');
    onClose();
  };
  const choose = (suggestion: Suggestion) => {
    remember(suggestion);
    onSelect(suggestion);
    close();
  };

  const locateHere = async () => {
    setHere('locating');
    const position = await getCoarsePosition();
    if (position.status !== 'granted') {
      setHere(position.status);
      return;
    }
    try {
      const destination = await resolveDestination(getApiClient(), position.fix);
      setHere('idle');
      choose({ type: 'destination', destination });
    } catch (error) {
      setHere(
        error instanceof ApiProblem && error.code === 'location_unresolvable'
          ? 'uncovered'
          : 'failed',
      );
    }
  };

  const row = (suggestion: Suggestion, rowTestID: string, kindLabel: string) => {
    const name = suggestion.type === 'place' ? suggestion.place.name : suggestion.destination.name;
    const where = whereIs(suggestion);
    return (
      <Pressable
        key={suggestionKey(suggestion)}
        onPress={() => choose(suggestion)}
        accessibilityRole="button"
        accessibilityLabel={[name, kindLabel, where].filter(Boolean).join(', ')}
        style={({ pressed }) => [
          styles.row,
          { borderColor: theme.colors.divider, opacity: pressed ? 0.6 : 1 },
        ]}
        testID={rowTestID}
      >
        <View style={[styles.icon, { backgroundColor: theme.colors.surface }]}>
          <Ionicons name={iconFor(suggestion)} size={18} color={theme.colors.textPrimary} />
        </View>
        <View style={styles.texts}>
          <Text
            numberOfLines={1}
            style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}
          >
            {name}
          </Text>
          {where ? (
            <Text
              numberOfLines={1}
              style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
            >
              {where}
            </Text>
          ) : null}
        </View>
      </Pressable>
    );
  };
  const kindLabel = (suggestion: Suggestion) =>
    suggestion.type === 'place'
      ? t('search.kind.place')
      : suggestion.destination.kind === 'country'
        ? t('search.kind.country')
        : suggestion.destination.kind === 'city'
          ? t('search.kind.city')
          : t('search.kind.area');
  const rowFor = (suggestion: Suggestion, prefix: string) =>
    row(
      suggestion,
      suggestion.type === 'place'
        ? `${testID}-place-${suggestion.place.id}`
        : `${prefix}${suggestion.destination.slug}`,
      kindLabel(suggestion),
    );
  const heading = (text: string) => (
    <Text
      accessibilityRole="header"
      style={[theme.typography.label, styles.heading, { color: theme.colors.textSecondary }]}
    >
      {text}
    </Text>
  );

  const found = (results.data ?? []).filter(allowed);
  const remembered = (recents ?? []).filter(allowed);
  const hereMessage =
    here === 'denied'
      ? t('search.locationDenied')
      : here === 'unavailable'
        ? t('search.locationUnavailable')
        : here === 'uncovered'
          ? t('search.uncovered')
          : here === 'failed'
            ? t('search.failed')
            : null;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={close}
      presentationStyle="fullScreen"
    >
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <View style={[styles.bar, { borderColor: theme.colors.divider }]}>
          <Pressable
            onPress={close}
            accessibilityRole="button"
            accessibilityLabel={t('search.close')}
            hitSlop={12}
            testID={`${testID}-close`}
          >
            <Ionicons name="arrow-back" size={24} color={theme.colors.textPrimary} />
          </Pressable>
          <View
            style={[
              styles.field,
              { backgroundColor: theme.colors.surface, borderRadius: theme.radii.md },
            ]}
          >
            <Ionicons name="search" size={18} color={theme.colors.textSecondary} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              autoFocus
              autoCorrect={false}
              autoCapitalize="words"
              returnKeyType="search"
              placeholder={title ?? t('search.placeholder')}
              placeholderTextColor={theme.colors.textSecondary}
              selectionColor={theme.colors.primary}
              cursorColor={theme.colors.primary}
              accessibilityLabel={title ?? t('search.placeholder')}
              style={[theme.typography.body, styles.input, { color: theme.colors.textPrimary }]}
              testID={`${testID}-input`}
            />
            {query ? (
              <Pressable
                onPress={() => setQuery('')}
                accessibilityRole="button"
                accessibilityLabel={t('search.clear')}
                hitSlop={10}
                testID={`${testID}-clear`}
              >
                <Ionicons name="close-circle" size={18} color={theme.colors.textSecondary} />
              </Pressable>
            ) : null}
          </View>
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.list}>
          {searching ? (
            <>
              {results.isFetching && found.length === 0 ? (
                <ActivityIndicator color={theme.colors.primary} style={styles.spinner} />
              ) : null}
              {found.map((item) => rowFor(item, `${testID}-`))}
              {results.isError && found.length === 0 ? (
                <View style={styles.message}>
                  <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                    {t('search.failed')}
                  </Text>
                  <Pressable
                    onPress={() => void results.refetch()}
                    accessibilityRole="button"
                    testID={`${testID}-retry`}
                  >
                    <Text style={[theme.typography.bodyStrong, { color: theme.colors.primary }]}>
                      {t('search.retry')}
                    </Text>
                  </Pressable>
                </View>
              ) : null}
              {results.isSuccess && !results.isFetching && found.length === 0 ? (
                <Text
                  style={[
                    theme.typography.body,
                    styles.message,
                    { color: theme.colors.textSecondary },
                  ]}
                  testID={`${testID}-empty`}
                >
                  {t('search.noResults', { query: term })}
                </Text>
              ) : null}
            </>
          ) : (
            <>
              {signedIn ? (
                <Pressable
                  onPress={() => void locateHere()}
                  disabled={here === 'locating'}
                  accessibilityRole="button"
                  style={({ pressed }) => [
                    styles.row,
                    { borderColor: theme.colors.divider, opacity: pressed ? 0.6 : 1 },
                  ]}
                  testID={`${testID}-here`}
                >
                  <View style={[styles.icon, { backgroundColor: theme.colors.primary }]}>
                    {here === 'locating' ? (
                      <ActivityIndicator size="small" color={theme.colors.onPrimary} />
                    ) : (
                      <Ionicons name="navigate" size={18} color={theme.colors.onPrimary} />
                    )}
                  </View>
                  <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                    {here === 'locating' ? t('search.locating') : t('search.currentLocation')}
                  </Text>
                </Pressable>
              ) : null}
              {hereMessage ? (
                <Text
                  style={[
                    theme.typography.caption,
                    styles.message,
                    { color: theme.colors.textSecondary },
                  ]}
                  testID={`${testID}-here-message`}
                >
                  {hereMessage}
                </Text>
              ) : null}
              {remembered.length > 0 ? heading(t('search.recent')) : null}
              {remembered.map((item) => rowFor(item, `${testID}-recent-`))}
              {(popular.data ?? []).length > 0 ? heading(t('search.popular')) : null}
              {(popular.data ?? []).map((destination) =>
                rowFor({ type: 'destination', destination }, `${testID}-popular-`),
              )}
            </>
          )}
          <Text
            style={[theme.typography.caption, styles.credit, { color: theme.colors.textSecondary }]}
          >
            {t('search.credit')}
          </Text>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  field: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    minHeight: 44,
  },
  input: { flex: 1, paddingVertical: 8 },
  list: { paddingHorizontal: 16, paddingBottom: 32 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: 56,
  },
  icon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  texts: { flex: 1, gap: 2 },
  heading: { marginTop: 20, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.8 },
  message: { paddingVertical: 12, gap: 8 },
  spinner: { marginVertical: 16 },
  credit: { marginTop: 24, textAlign: 'center' },
});
