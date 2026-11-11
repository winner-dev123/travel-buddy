import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AccessibilityInfo,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { DiscoverySafetyNotice } from '@/components/DiscoverySafetyNotice';
import { Button, Notice, TextField } from '@/components/Form';
import { refreshMe, sendConnectionRequest } from '@/features/account/api';
import { exploreKeys, getDestination, type DestinationDetail } from '@/features/explore/api';
import { searchDestinations } from '@/features/feed/api';
import { getCoarsePosition } from '@/features/feed/location';
import { Avatar } from '@/features/feed/PostCard';
import { scrims } from '@/theme/tokens';
import { useAppTheme } from '@/theme/useAppTheme';
import { useReduceMotion } from '@/theme/useReduceMotion';

import {
  disableDiscovery,
  discoverTravelers,
  discoveryKeys,
  fetchApproximateLocation,
  fetchSession,
  shareLocation,
  stopSharing,
  type DiscoverySession,
  type ShareTarget,
  type TravelerCard,
} from './api';
import { CompanionMap } from './map/CompanionMap';
import { SWEEP_MS, type GeoPoint, type MapPin } from './map/mapPage';
import { CITY_VIEW_RADIUS_M, COUNTRY_VIEW_RADIUS_M, layoutPins } from './map/pinLayout';

/** A search lasts at least one turn of the radar, so the sweep can reveal what it found. */
export const SCAN_MIN_MS = SWEEP_MS + 300;
const IP_CREDIT_URL = 'https://db-ip.com';

interface ScanResult {
  /** The discovery session the search ran in: results go away with it. */
  sessionId: string;
  destinationId: string;
  place: string;
  cards: TravelerCard[];
}

function TravelerRow({ card, onOpen }: { card: TravelerCard; onOpen: () => void }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const key = useRef(getApiClient().newIdempotencyKey());
  const [sent, setSent] = useState(card.relationship === 'request_pending');
  const connect = useMutation({
    mutationFn: () => sendConnectionRequest(getApiClient(), card.user.id, key.current, 'discovery'),
    onSuccess: () => setSent(true),
  });
  const chips = [...card.shared.interests, ...card.shared.travel_styles];
  const where = card.presence.area?.name ?? card.presence.destination.name;
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.background,
          borderColor: theme.colors.divider,
          borderRadius: theme.radii.lg,
          padding: theme.spacing[3],
          gap: theme.spacing[2],
        },
      ]}
      testID={`traveler-${card.user.id}`}
    >
      <Pressable
        onPress={onOpen}
        accessibilityRole="link"
        accessibilityLabel={`${card.user.display_name}, ${where}`}
        style={styles.row}
      >
        <Avatar user={card.user} size={44} ring />
        <View style={styles.fill}>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {card.user.display_name}
          </Text>
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t(`discovery.compatibility.${card.compatibility}`)} · {where}
          </Text>
        </View>
        <Ionicons
          name="chevron-forward"
          size={18}
          color={theme.colors.textSecondary}
          accessible={false}
        />
      </Pressable>
      {card.bio_snippet ? (
        <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {card.bio_snippet}
        </Text>
      ) : null}
      {chips.length ? (
        <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>
          {t('discovery.shared', { items: chips.join(', ') })}
        </Text>
      ) : null}
      {card.relationship === 'connected' ? (
        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('user.connected')}
        </Text>
      ) : sent ? (
        <Text
          style={[theme.typography.label, { color: theme.colors.textSecondary }]}
          testID={`traveler-sent-${card.user.id}`}
        >
          {t('user.requestSent')}
        </Text>
      ) : card.can_request_connection ? (
        <Button
          label={t('user.connect')}
          variant="secondary"
          icon="person-add-outline"
          onPress={() => connect.mutate()}
          busy={connect.isPending}
          testID={`traveler-connect-${card.user.id}`}
        />
      ) : null}
      {connect.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
    </View>
  );
}

function initialOf(name: string): string {
  return (name.trim().charAt(0) || '?').toUpperCase();
}

/**
 * Companions map and traveler discovery (DISC-001..012, LOC-010, ADR-0030).
 *
 * The map starts around the city the connection points to, or where the traveller is already
 * visible. "Search for companions" shares that city (only then does anyone become discoverable),
 * sweeps the radar and shows each traveller in the area they share, never at a position.
 */
export function DiscoverSection() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const reduceMotion = useReduceMotion();
  const { height: windowHeight } = useWindowDimensions();
  const enabled = useSessionStore((state) => state.me?.privacy.discovery_enabled ?? false);
  const [search, setSearch] = useState('');
  const [picking, setPicking] = useState(false);
  const [lastScan, setLastScan] = useState<ScanResult | null>(null);
  const [scanId, setScanId] = useState(0);
  const [mapUnavailable, setMapUnavailable] = useState(false);

  const approximate = useQuery({
    queryKey: discoveryKeys.approximate,
    queryFn: () => fetchApproximateLocation(getApiClient()),
    staleTime: 15 * 60_000,
  });
  const here = approximate.data ?? null;
  const session = useQuery({
    queryKey: discoveryKeys.session,
    queryFn: () => fetchSession(getApiClient()),
    enabled,
  });
  const current: DiscoverySession | null = enabled ? (session.data ?? null) : null;
  const visible = current?.visibility === 'visible';
  const sessionCityId = current?.destination.id;
  const sharedCity = useQuery({
    queryKey: exploreKeys.destination(sessionCityId ?? ''),
    queryFn: () => getDestination(getApiClient(), sessionCityId ?? ''),
    enabled: !!sessionCityId && sessionCityId !== here?.destination?.id,
    staleTime: Infinity,
  });
  const cityCentre: GeoPoint | null = current
    ? current.destination.id === here?.destination?.id
      ? here.destination.centroid
      : (sharedCity.data?.centroid ?? null)
    : null;

  const view = current
    ? cityCentre
      ? { center: cityCentre, radiusM: CITY_VIEW_RADIUS_M }
      : null
    : here
      ? {
          center: here.center,
          radiusM: here.precision === 'city' ? CITY_VIEW_RADIUS_M : COUNTRY_VIEW_RADIUS_M,
        }
      : null;
  const place = current
    ? [current.area?.name, current.destination.name].filter(Boolean).join(', ')
    : (here?.label ?? null);
  const searchCity = current?.destination ?? here?.destination ?? null;
  const uncovered = !current && !!here && !here.destination;
  const unknown = !current && approximate.isFetched && !here;

  // Results belong to the session they were found in (a new city or visibility means a new one).
  const found = lastScan && current?.id === lastScan.sessionId && visible ? lastScan : null;

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['discovery'] });

  const scan = useMutation({
    mutationFn: async (): Promise<ScanResult> => {
      const client = getApiClient();
      const started = Date.now();
      let active = current;
      if (!active) {
        const city = here?.destination;
        if (!city) throw new Error('uncovered');
        // Becoming discoverable is this explicit step, never the IP lookup (LOC-004).
        active = await shareLocation(client, { mode: 'destination', destinationId: city.id });
        queryClient.setQueryData(discoveryKeys.session, active);
      }
      const cards = await discoverTravelers(client);
      // Public centres of the city and the shared neighbourhoods, for the pins.
      const ids = new Set([active.destination.id]);
      cards.forEach((card) => card.presence.area && ids.add(card.presence.area.id));
      await Promise.all(
        [...ids].map((id) =>
          queryClient.fetchQuery({
            queryKey: exploreKeys.destination(id),
            queryFn: () => getDestination(client, id),
            staleTime: Infinity,
          }),
        ),
      );
      const rest = (reduceMotion ? 0 : SCAN_MIN_MS) - (Date.now() - started);
      if (rest > 0) await new Promise((resolve) => setTimeout(resolve, rest));
      return {
        sessionId: active.id,
        destinationId: active.destination.id,
        place: active.destination.name,
        cards,
      };
    },
    onMutate: () => {
      setLastScan(null);
      setPicking(false);
      setScanId((id) => id + 1);
    },
    onSuccess: (result) => {
      setLastScan(result);
      AccessibilityInfo.announceForAccessibility(
        result.cards.length
          ? t('discovery.found', { count: result.cards.length, place: result.place })
          : t('discovery.nobody'),
      );
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: discoveryKeys.session }),
  });

  const pins = useMemo<MapPin[] | null>(() => {
    if (!found) return null;
    const centres = new Map<string, GeoPoint>();
    const anchors = found.cards.map((card) => ({
      id: card.user.id,
      anchorId: card.presence.area?.id ?? found.destinationId,
      anchorKind: card.presence.area ? ('neighborhood' as const) : ('city' as const),
    }));
    for (const { anchorId } of anchors) {
      const centre = queryClient.getQueryData<DestinationDetail>(
        exploreKeys.destination(anchorId),
      )?.centroid;
      if (centre) centres.set(anchorId, centre);
    }
    const placed = layoutPins(anchors, centres);
    return found.cards.flatMap((card) => {
      const at = placed.get(card.user.id);
      if (!at) return [];
      return [
        {
          id: card.user.id,
          name: card.user.display_name,
          initial: initialOf(card.user.display_name),
          avatarUrl: card.user.avatar?.status === 'ready' ? card.user.avatar.url : null,
          lat: at.lat,
          lng: at.lng,
          label: t('discovery.openProfile', { name: card.user.display_name }),
        },
      ];
    });
  }, [found, queryClient, t]);

  const matches = useQuery({
    queryKey: ['destinations', 'search', search],
    queryFn: () => searchDestinations(getApiClient(), search),
    enabled: enabled && search.trim().length >= 2,
  });
  const share = useMutation({
    mutationFn: async (target: ShareTarget | 'gps') => {
      if (target === 'gps') {
        const position = await getCoarsePosition();
        if (position.status !== 'granted') throw new Error(position.status);
        return shareLocation(getApiClient(), {
          mode: 'gps',
          near: position.near,
          fix: position.fix,
        });
      }
      return shareLocation(getApiClient(), target);
    },
    onSuccess: () => {
      setPicking(false);
      setSearch('');
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (active: DiscoverySession) =>
      shareLocation(
        getApiClient(),
        { mode: 'destination', destinationId: active.area?.id ?? active.destination.id },
        active.visibility === 'visible' ? 'invisible' : 'visible',
      ),
    onSuccess: refresh,
  });
  const stop = useMutation({ mutationFn: () => stopSharing(getApiClient()), onSuccess: refresh });
  const turnOff = useMutation({
    mutationFn: async () => {
      const client = getApiClient();
      await stopSharing(client);
      await disableDiscovery(client);
      await refreshMe(client);
    },
    onSuccess: refresh,
  });

  const openProfile = (id: string) => router.push({ pathname: '/user/[id]', params: { id } });
  const mapHeight = Math.round(Math.min(440, Math.max(300, windowHeight * 0.46)));
  const body = (value: string, testID?: string) => (
    <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]} testID={testID}>
      {value}
    </Text>
  );

  const chipTitle = current
    ? t(visible ? 'discovery.mapVisible' : 'discovery.mapInvisible', { place })
    : here
      ? t('discovery.mapAround', { place: here.label })
      : t('discovery.mapNoLocation');

  const map = (
    <View style={{ gap: theme.spacing[2] }}>
      <CompanionMap
        view={view}
        scanId={scanId}
        scanning={scan.isPending}
        pins={pins}
        onOpen={openProfile}
        onUnavailable={setMapUnavailable}
        height={mapHeight}
        accessibilityLabel={
          place ? t('discovery.mapA11y', { place }) : t('discovery.mapNoLocation')
        }
      >
        <View
          style={[
            styles.chip,
            {
              backgroundColor: scrims.photoChip,
              borderRadius: theme.radii.lg,
              margin: theme.spacing[3],
              paddingHorizontal: theme.spacing[3],
              paddingVertical: theme.spacing[2],
            },
          ]}
          testID="discovery-location-label"
        >
          <Ionicons
            name={current ? 'radio-outline' : 'navigate'}
            size={16}
            color={scrims.onPhoto}
            accessible={false}
          />
          <View style={styles.chipText}>
            <Text style={[theme.typography.label, { color: scrims.onPhoto }]} numberOfLines={1}>
              {chipTitle}
            </Text>
            {!current && here ? (
              <Text style={[theme.typography.caption, { color: scrims.onPhoto }]}>
                {t('discovery.mapApproximate')}
              </Text>
            ) : null}
          </View>
        </View>
        {mapUnavailable ? (
          <View
            style={[
              styles.mapNotice,
              { backgroundColor: scrims.photoChip, borderRadius: theme.radii.md },
            ]}
            testID="discovery-map-unavailable"
          >
            <Text style={[theme.typography.caption, { color: scrims.onPhoto }]}>
              {t('discovery.mapUnavailable')}
            </Text>
          </View>
        ) : null}
      </CompanionMap>
      {pins && pins.length > 0 ? (
        <View style={styles.legend} testID="discovery-map-legend">
          <Ionicons
            name="information-circle-outline"
            size={14}
            color={theme.colors.textSecondary}
            accessible={false}
          />
          <Text
            style={[theme.typography.caption, styles.fill, { color: theme.colors.textSecondary }]}
          >
            {t('discovery.mapLegend')}
          </Text>
        </View>
      ) : null}
      {here && !current ? (
        <Pressable
          onPress={() => void Linking.openURL(IP_CREDIT_URL)}
          accessibilityRole="link"
          style={styles.credit}
          testID="discovery-ip-credit"
        >
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('discovery.ipCredit')}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );

  if (!enabled) {
    return (
      <View style={{ gap: theme.spacing[4] }} testID="discovery-off">
        {map}
        <View
          style={[
            styles.section,
            {
              backgroundColor: theme.colors.surface,
              borderColor: theme.colors.divider,
              borderRadius: theme.radii.lg,
              padding: theme.spacing[4],
              gap: theme.spacing[3],
            },
          ]}
        >
          <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
            {t('discovery.offTitle')}
          </Text>
          {body(t('discovery.offBody'))}
          <DiscoverySafetyNotice />
          <Button
            label={t('discovery.turnOn')}
            icon="radio-outline"
            onPress={() => router.push('/discovery/consent')}
            testID="discovery-open-consent"
          />
        </View>
      </View>
    );
  }

  const shareError =
    share.error instanceof ApiProblem && share.error.code === 'location_unresolvable'
      ? t('discovery.uncovered')
      : share.error instanceof Error && share.error.message === 'denied'
        ? t('feed.nearby.denied')
        : share.isError
          ? t('user.actionFailed')
          : null;
  const scanError = scan.isError
    ? scan.error instanceof Error && scan.error.message === 'uncovered'
      ? t('discovery.notCovered', { place: here?.label ?? '' })
      : t('user.actionFailed')
    : null;
  const showPicker = picking || (!current && (uncovered || unknown));
  const canSearch = !!searchCity && (!current || visible) && !!view;

  return (
    <View style={{ gap: theme.spacing[4] }} testID="discovery-on">
      {map}
      <Button
        label={scan.isPending ? t('discovery.scanning') : t('discovery.search')}
        icon="radio-outline"
        onPress={() => {
          if (!scan.isPending) scan.mutate();
        }}
        disabled={!canSearch && !scan.isPending}
        testID="discovery-search-companions"
      />
      {uncovered ? (
        <Notice tone="info" testID="discovery-not-covered">
          {t('discovery.notCovered', { place: here?.label ?? '' })}
        </Notice>
      ) : null}
      {current && !visible ? <Notice tone="info">{t('discovery.invisibleNote')}</Notice> : null}
      {scanError ? <Notice tone="error">{scanError}</Notice> : null}
      {found ? (
        <View style={{ gap: theme.spacing[3] }}>
          {found.cards.length === 0 ? (
            body(t('discovery.nobody'), 'discovery-nobody')
          ) : (
            <>
              <Text
                accessibilityRole="header"
                style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                testID="discovery-found"
              >
                {t('discovery.found', { count: found.cards.length, place: found.place })}
              </Text>
              {found.cards.map((card) => (
                <TravelerRow
                  key={card.user.id}
                  card={card}
                  onOpen={() => openProfile(card.user.id)}
                />
              ))}
            </>
          )}
        </View>
      ) : null}
      <View
        style={[
          styles.section,
          {
            backgroundColor: theme.colors.surface,
            borderColor: theme.colors.divider,
            borderRadius: theme.radii.lg,
            padding: theme.spacing[4],
            gap: theme.spacing[3],
          },
        ]}
      >
        {current ? (
          <>
            {body(
              t(visible ? 'discovery.visibleIn' : 'discovery.invisibleIn', {
                place,
                time: new Date(current.expires_at).toLocaleString(i18n.language, {
                  weekday: 'short',
                  hour: '2-digit',
                  minute: '2-digit',
                }),
              }),
              'discovery-status',
            )}
            <View style={[styles.actions, { gap: theme.spacing[2] }]}>
              <View style={styles.fill}>
                <Button
                  label={visible ? t('discovery.goInvisible') : t('discovery.goVisible')}
                  variant="secondary"
                  onPress={() => toggle.mutate(current)}
                  busy={toggle.isPending}
                  testID="discovery-toggle-visibility"
                />
              </View>
              <View style={styles.fill}>
                <Button
                  label={t('discovery.stop')}
                  variant="secondary"
                  onPress={() => stop.mutate()}
                  busy={stop.isPending}
                  testID="discovery-stop"
                />
              </View>
            </View>
          </>
        ) : null}
        {showPicker ? (
          <>
            {body(t('discovery.shareTitle'))}
            <Button
              label={t('discovery.shareGps')}
              variant="secondary"
              icon="locate-outline"
              onPress={() => share.mutate('gps')}
              busy={share.isPending}
              testID="discovery-share-gps"
            />
            <TextField
              label={t('discovery.shareCity')}
              value={search}
              onChangeText={setSearch}
              autoCorrect={false}
              testID="discovery-search"
            />
            {(matches.data ?? []).map((match) => (
              <Pressable
                key={match.id}
                onPress={() => share.mutate({ mode: 'destination', destinationId: match.id })}
                accessibilityRole="button"
                style={[
                  styles.match,
                  { borderColor: theme.colors.divider, borderRadius: theme.radii.md },
                ]}
                testID={`discovery-match-${match.slug}`}
              >
                {body([match.name, match.country_name].filter(Boolean).join(', '))}
              </Pressable>
            ))}
            {shareError ? <Notice tone="info">{shareError}</Notice> : null}
          </>
        ) : (
          <Button
            label={t('discovery.changeCity')}
            variant="ghost"
            icon="swap-horizontal-outline"
            onPress={() => setPicking(true)}
            testID="discovery-change-city"
          />
        )}
        <Button
          label={t('discovery.turnOff')}
          variant="ghost"
          onPress={() => turnOff.mutate()}
          busy={turnOff.isPending}
          testID="discovery-turn-off"
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  section: { borderWidth: StyleSheet.hairlineWidth },
  card: { borderWidth: StyleSheet.hairlineWidth },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  actions: { flexDirection: 'row' },
  match: { borderWidth: StyleSheet.hairlineWidth, padding: 12 },
  chip: {
    position: 'absolute',
    top: 0,
    left: 0,
    maxWidth: '86%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  chipText: { flexShrink: 1 },
  legend: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
  mapNotice: {
    position: 'absolute',
    alignSelf: 'center',
    top: '45%',
    marginHorizontal: 24,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  credit: { alignSelf: 'flex-end', minHeight: 24, justifyContent: 'center' },
});
