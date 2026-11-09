import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { DiscoverySafetyNotice } from '@/components/DiscoverySafetyNotice';
import { Button, Notice, TextField } from '@/components/Form';
import { refreshMe, sendConnectionRequest } from '@/features/account/api';
import { searchDestinations } from '@/features/feed/api';
import { getCoarsePosition } from '@/features/feed/location';
import { Avatar } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

import {
  disableDiscovery,
  discoverTravelers,
  discoveryKeys,
  fetchSession,
  shareLocation,
  stopSharing,
  type DiscoverySession,
  type ShareTarget,
  type TravelerCard,
} from './api';

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
  return (
    <View
      style={[styles.card, { borderColor: theme.colors.divider }]}
      testID={`traveler-${card.user.id}`}
    >
      <Pressable onPress={onOpen} accessibilityRole="link" style={styles.row}>
        <Avatar user={card.user} />
        <View style={styles.fill}>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {card.user.display_name}
          </Text>
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t(`discovery.compatibility.${card.compatibility}`)}
            {card.presence.area ? ` · ${card.presence.area.name}` : ''}
          </Text>
        </View>
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
          onPress={() => connect.mutate()}
          busy={connect.isPending}
          testID={`traveler-connect-${card.user.id}`}
        />
      ) : null}
      {connect.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
    </View>
  );
}

/** Traveler discovery inside Companions (DISC-001..010): opt in, share a city, see who's here. */
export function DiscoverSection() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const enabled = useSessionStore((state) => state.me?.privacy.discovery_enabled ?? false);
  const [search, setSearch] = useState('');

  const session = useQuery({
    queryKey: discoveryKeys.session,
    queryFn: () => fetchSession(getApiClient()),
    enabled,
  });
  const current: DiscoverySession | null | undefined = session.data;
  const visible = current?.visibility === 'visible';
  const travelers = useQuery({
    queryKey: discoveryKeys.travelers(current?.destination.id),
    queryFn: () => discoverTravelers(getApiClient()),
    enabled: enabled && visible,
  });
  const matches = useQuery({
    queryKey: ['destinations', 'search', search],
    queryFn: () => searchDestinations(getApiClient(), search),
    enabled: enabled && !current && search.trim().length >= 2,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['discovery'] });
  const share = useMutation({
    mutationFn: async (target: ShareTarget | 'gps') => {
      if (target === 'gps') {
        const position = await getCoarsePosition();
        if (position.status !== 'granted') throw new Error(position.status);
        return shareLocation(getApiClient(), { mode: 'gps', near: position.near });
      }
      return shareLocation(getApiClient(), target);
    },
    onSuccess: refresh,
  });
  const toggle = useMutation({
    mutationFn: (session: DiscoverySession) =>
      shareLocation(
        getApiClient(),
        { mode: 'destination', destinationId: session.area?.id ?? session.destination.id },
        session.visibility === 'visible' ? 'invisible' : 'visible',
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

  const text = (value: string, testID?: string) => (
    <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]} testID={testID}>
      {value}
    </Text>
  );

  if (!enabled) {
    return (
      <View
        style={[styles.section, { backgroundColor: theme.colors.surface }]}
        testID="discovery-off"
      >
        <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
          {t('discovery.offTitle')}
        </Text>
        {text(t('discovery.offBody'))}
        <DiscoverySafetyNotice />
        <Button
          label={t('discovery.turnOn')}
          onPress={() => router.push('/discovery/consent')}
          testID="discovery-open-consent"
        />
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

  return (
    <View style={[styles.section, { backgroundColor: theme.colors.surface }]} testID="discovery-on">
      {!current ? (
        <>
          {text(t('discovery.shareTitle'))}
          <Button
            label={t('discovery.shareGps')}
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
              style={[styles.match, { borderColor: theme.colors.divider }]}
              testID={`discovery-match-${match.slug}`}
            >
              {text([match.name, match.country_name].filter(Boolean).join(', '))}
            </Pressable>
          ))}
          {shareError ? <Notice tone="info">{shareError}</Notice> : null}
        </>
      ) : (
        <>
          {text(
            t(visible ? 'discovery.visibleIn' : 'discovery.invisibleIn', {
              place: [current.area?.name, current.destination.name].filter(Boolean).join(', '),
              time: new Date(current.expires_at).toLocaleString(i18n.language, {
                weekday: 'short',
                hour: '2-digit',
                minute: '2-digit',
              }),
            }),
            'discovery-status',
          )}
          <View style={styles.actions}>
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
          {visible ? (
            (travelers.data ?? []).length === 0 && travelers.isSuccess ? (
              text(t('discovery.nobody'), 'discovery-nobody')
            ) : (
              (travelers.data ?? []).map((card) => (
                <TravelerRow
                  key={card.user.id}
                  card={card}
                  onOpen={() =>
                    router.push({ pathname: '/user/[id]', params: { id: card.user.id } })
                  }
                />
              ))
            )
          ) : (
            <Notice tone="info">{t('discovery.invisibleNote')}</Notice>
          )}
        </>
      )}
      <Button
        label={t('discovery.turnOff')}
        variant="secondary"
        onPress={() => turnOff.mutate()}
        busy={turnOff.isPending}
        testID="discovery-turn-off"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  section: { borderRadius: 12, padding: 16, gap: 12 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  actions: { flexDirection: 'row', gap: 8 },
  match: { borderWidth: 1, borderRadius: 8, padding: 12 },
});
