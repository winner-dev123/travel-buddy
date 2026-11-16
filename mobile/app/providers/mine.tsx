import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { MenuGroup, MenuRow } from '@/components/MenuRow';
import { ServerFeature } from '@/features/flags/serverFlags';
import {
  acceptInvitation,
  listMyProviders,
  providerKeys,
  removeMember,
} from '@/features/providers/api';
import { useSessionStore } from '@/auth/sessionStore';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-166 "Offer your services": my guide and company profiles, team invitations, apply. */
export default function MyProvidersScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <MyProviders />
    </ServerFeature>
  );
}

function MyProviders() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useSessionStore((state) => state.me?.account.id ?? null);
  const mine = useQuery({
    queryKey: providerKeys.mine,
    queryFn: () => listMyProviders(getApiClient()),
  });
  const accept = useMutation({
    mutationFn: (providerId: string) => acceptInvitation(getApiClient(), providerId),
    onSuccess: (workspace) => {
      void queryClient.invalidateQueries({ queryKey: providerKeys.mine });
      router.push({ pathname: '/providers/workspace/[id]', params: { id: workspace.id } });
    },
  });
  const decline = useMutation({
    mutationFn: (providerId: string) => removeMember(getApiClient(), providerId, me as string),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: providerKeys.mine }),
  });
  const items = mine.data?.data ?? [];
  const active = items.filter((m) => m.status === 'active');
  const invited = items.filter((m) => m.status === 'invited');

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.mine.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
          {t('providers.mine.intro')}
        </Text>
        {mine.isError ? <Notice tone="error">{t('providers.loadFailed')}</Notice> : null}
        {invited.map((m) => (
          <View
            key={m.provider.id}
            style={[
              styles.invite,
              {
                borderColor: theme.colors.divider,
                borderRadius: theme.radii.md,
                padding: theme.spacing[3],
                gap: theme.spacing[2],
              },
            ]}
            testID={`invitation-${m.provider.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {t('providers.mine.invited', {
                name: m.provider.display_name,
                role: t(`providers.role.${m.role}`),
              })}
            </Text>
            <View style={styles.actions}>
              <Button
                label={t('providers.mine.accept')}
                onPress={() => accept.mutate(m.provider.id)}
                busy={accept.isPending && accept.variables === m.provider.id}
                testID={`invitation-accept-${m.provider.id}`}
              />
              <Button
                label={t('providers.mine.decline')}
                variant="secondary"
                onPress={() => decline.mutate(m.provider.id)}
                disabled={me === null}
                testID={`invitation-decline-${m.provider.id}`}
              />
            </View>
          </View>
        ))}
        {active.length > 0 ? (
          <MenuGroup title={t('providers.mine.profiles')}>
            {active.map((m) => (
              <MenuRow
                key={m.provider.id}
                icon={m.provider.kind === 'guide' ? 'person-outline' : 'business-outline'}
                label={m.provider.display_name}
                detail={t(`providers.providerStatus.${m.provider.status}`)}
                onPress={() =>
                  router.push({
                    pathname: '/providers/workspace/[id]',
                    params: { id: m.provider.id },
                  })
                }
                testID={`my-provider-${m.provider.id}`}
              />
            ))}
          </MenuGroup>
        ) : null}
        <Button
          label={t('providers.mine.apply')}
          icon="add-circle-outline"
          onPress={() => router.push('/providers/apply')}
          testID="providers-apply"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  invite: { borderWidth: StyleSheet.hairlineWidth },
  actions: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
});
