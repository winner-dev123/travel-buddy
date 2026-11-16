import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Chip } from '@/components/Chip';
import { Button, Notice, TextField } from '@/components/Form';
import { Avatar } from '@/features/feed/PostCard';
import { ServerFeature } from '@/features/flags/serverFlags';
import {
  getWorkspace,
  inviteMember,
  listMembers,
  providerKeys,
  removeMember,
} from '@/features/providers/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-172 A company's team: invite managers and agents by handle, remove, leave (PROV-005). */
export default function TeamScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <Team />
    </ServerFeature>
  );
}

function Team() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const me = useSessionStore((state) => state.me?.account.id ?? null);
  const [handle, setHandle] = useState('');
  const [role, setRole] = useState<'manager' | 'agent'>('agent');
  const workspace = useQuery({
    queryKey: providerKeys.workspace(id),
    queryFn: () => getWorkspace(getApiClient(), id),
  });
  const members = useQuery({
    queryKey: providerKeys.members(id),
    queryFn: () => listMembers(getApiClient(), id),
  });
  const myRole = workspace.data?.membership?.role;
  const invite = useMutation({
    mutationFn: () => inviteMember(getApiClient(), id, handle, role),
    onSuccess: (list) => {
      queryClient.setQueryData(providerKeys.members(id), list);
      setHandle('');
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removeMember(getApiClient(), id, userId),
    onSuccess: (_, userId) => {
      if (userId === me) {
        void queryClient.invalidateQueries({ queryKey: providerKeys.mine });
        router.replace('/providers/mine');
        return;
      }
      void members.refetch();
    },
  });
  const inviteProblem =
    invite.error instanceof ApiProblem
      ? invite.error.code === 'validation_failed'
        ? t('providers.team.noSuchHandle')
        : invite.error.code === 'conflict'
          ? t('providers.team.already')
          : t('providers.team.failed')
      : null;
  const canRemove = (target: string) =>
    target === 'owner' ? false : myRole === 'owner' || (myRole === 'manager' && target === 'agent');

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.workspace.team') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        {(members.data?.data ?? []).map((member) => (
          <View
            key={member.user?.id ?? member.created_at}
            style={[styles.row, { borderColor: theme.colors.divider }]}
            testID={`member-${member.user?.id}`}
          >
            <Avatar user={member.user} size={36} />
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {member.user?.display_name ?? t('providers.formerTraveler')}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {member.status === 'invited'
                  ? t('providers.team.pending', { role: t(`providers.role.${member.role}`) })
                  : t(`providers.role.${member.role}`)}
              </Text>
            </View>
            {member.user &&
            (member.user.id === me ? member.role !== 'owner' : canRemove(member.role)) ? (
              <Button
                label={
                  member.user.id === me ? t('providers.team.leave') : t('providers.team.remove')
                }
                variant="ghost"
                onPress={() =>
                  Alert.alert(
                    member.user?.id === me ? t('providers.team.leave') : t('providers.team.remove'),
                    undefined,
                    [
                      { text: t('common.cancel'), style: 'cancel' },
                      {
                        text: t('providers.team.confirm'),
                        style: 'destructive',
                        onPress: () => remove.mutate(member.user?.id as string),
                      },
                    ],
                  )
                }
                testID={`member-remove-${member.user.id}`}
              />
            ) : null}
          </View>
        ))}
        {myRole === 'owner' || myRole === 'manager' ? (
          <View style={{ gap: theme.spacing[2] }}>
            <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
              {t('providers.team.invite')}
            </Text>
            <TextField
              label={t('providers.team.handle')}
              value={handle}
              onChangeText={setHandle}
              autoCapitalize="none"
              autoCorrect={false}
              maxLength={40}
              testID="team-handle"
            />
            <View style={styles.chips}>
              {(myRole === 'owner' ? (['agent', 'manager'] as const) : (['agent'] as const)).map(
                (value) => (
                  <Chip
                    key={value}
                    label={t(`providers.role.${value}`)}
                    selected={role === value}
                    onPress={() => setRole(value)}
                    testID={`team-role-${value}`}
                  />
                ),
              )}
            </View>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t(`providers.team.roleHelp.${role}`)}
            </Text>
            {inviteProblem ? <Notice tone="error">{inviteProblem}</Notice> : null}
            <Button
              label={t('providers.team.send')}
              onPress={() => invite.mutate()}
              disabled={handle.trim().length < 2}
              busy={invite.isPending}
              testID="team-invite"
            />
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 8,
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
