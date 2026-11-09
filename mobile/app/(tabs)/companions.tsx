import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { DiscoverySafetyNotice } from '@/components/DiscoverySafetyNotice';
import { DiscoverSection } from '@/features/discovery/DiscoverSection';
import { FeatureGate } from '@/components/FeatureGate';
import { Button, Notice } from '@/components/Form';
import {
  accountKeys,
  listConnectionRequests,
  listConnections,
  respondToRequest,
  type ConnectionRequest,
} from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import type { UserSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/**
 * SCR-060 Companions: connection requests and connections now; opt-in traveler discovery and
 * groups arrive later (Phase 2–3). The safety guidance is real copy and is always shown.
 */
export default function CompanionsScreen() {
  return (
    <FeatureGate feature="companions" placeholderExtra={<DiscoverySafetyNotice />}>
      <Companions />
    </FeatureGate>
  );
}

function PersonRow({
  user,
  onOpen,
  children,
  testID,
}: {
  user: UserSummary;
  onOpen: () => void;
  children?: React.ReactNode;
  testID?: string;
}) {
  const theme = useAppTheme();
  return (
    <View style={styles.row} testID={testID}>
      <Pressable
        onPress={onOpen}
        accessibilityRole="link"
        accessibilityLabel={user.display_name}
        style={styles.person}
      >
        <Avatar user={user} />
        <View style={styles.fill}>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {user.display_name}
          </Text>
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            @{user.handle}
          </Text>
        </View>
      </Pressable>
      {children}
    </View>
  );
}

function Companions() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const incoming = useQuery({
    queryKey: accountKeys.requests('incoming'),
    queryFn: () => listConnectionRequests(getApiClient(), 'incoming'),
    enabled: signedIn,
  });
  const outgoing = useQuery({
    queryKey: accountKeys.requests('outgoing'),
    queryFn: () => listConnectionRequests(getApiClient(), 'outgoing'),
    enabled: signedIn,
  });
  const connections = useQuery({
    queryKey: accountKeys.connections,
    queryFn: () => listConnections(getApiClient()),
    enabled: signedIn,
  });
  const respond = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'accept' | 'decline' | 'cancel' }) =>
      respondToRequest(getApiClient(), id, action),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['me', 'connection-requests'] });
      void queryClient.invalidateQueries({ queryKey: accountKeys.connections });
    },
  });
  const open = (user: UserSummary) =>
    router.push({ pathname: '/user/[id]', params: { id: user.id } });

  const heading = (text: string) => (
    <Text
      accessibilityRole="header"
      style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
    >
      {text}
    </Text>
  );
  const empty = (text: string, testID: string) => (
    <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]} testID={testID}>
      {text}
    </Text>
  );
  const busy = (request: ConnectionRequest) =>
    respond.isPending && respond.variables?.id === request.id;

  return (
    <SafeAreaView
      edges={['top']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[4] }}>
        <Text
          accessibilityRole="header"
          style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
        >
          {t('companions.title')}
        </Text>
        {signedIn ? (
          <DiscoverSection />
        ) : (
          <View
            style={[styles.card, { backgroundColor: theme.colors.surface, gap: theme.spacing[3] }]}
          >
            <DiscoverySafetyNotice />
          </View>
        )}
        {!signedIn ? (
          <View style={{ gap: theme.spacing[3] }}>
            <Notice tone="info">{t('companions.signIn')}</Notice>
            <Button label={t('account.goToSignIn')} onPress={() => router.push('/sign-in')} />
          </View>
        ) : (
          <>
            {respond.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
            {heading(t('companions.incoming'))}
            {(incoming.data?.data ?? []).length === 0
              ? empty(t('companions.noIncoming'), 'companions-no-incoming')
              : (incoming.data?.data ?? []).map((request) => (
                  <View key={request.id} style={{ gap: theme.spacing[2] }}>
                    <PersonRow
                      user={request.requester}
                      onOpen={() => open(request.requester)}
                      testID={`incoming-${request.id}`}
                    />
                    {request.note ? (
                      <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                        “{request.note}”
                      </Text>
                    ) : null}
                    <View style={styles.actions}>
                      <View style={styles.fill}>
                        <Button
                          label={t('companions.accept')}
                          onPress={() => respond.mutate({ id: request.id, action: 'accept' })}
                          busy={busy(request)}
                          testID={`accept-${request.id}`}
                        />
                      </View>
                      <View style={styles.fill}>
                        <Button
                          label={t('companions.decline')}
                          variant="secondary"
                          onPress={() => respond.mutate({ id: request.id, action: 'decline' })}
                          testID={`decline-${request.id}`}
                        />
                      </View>
                    </View>
                  </View>
                ))}
            {(outgoing.data?.data ?? []).length > 0 ? (
              <>
                {heading(t('companions.outgoing'))}
                {(outgoing.data?.data ?? []).map((request) => (
                  <PersonRow
                    key={request.id}
                    user={request.recipient}
                    onOpen={() => open(request.recipient)}
                    testID={`outgoing-${request.id}`}
                  >
                    <Button
                      label={t('companions.cancel')}
                      variant="secondary"
                      onPress={() => respond.mutate({ id: request.id, action: 'cancel' })}
                      busy={busy(request)}
                      testID={`cancel-${request.id}`}
                    />
                  </PersonRow>
                ))}
              </>
            ) : null}
            {heading(t('companions.connections'))}
            {(connections.data?.data ?? []).length === 0
              ? empty(t('companions.noConnections'), 'companions-no-connections')
              : (connections.data?.data ?? []).map((connection) => (
                  <PersonRow
                    key={connection.user.id}
                    user={connection.user}
                    onOpen={() => open(connection.user)}
                    testID={`connection-${connection.user.id}`}
                  />
                ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderRadius: 12, padding: 16 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  person: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 },
  actions: { flexDirection: 'row', gap: 8 },
});
