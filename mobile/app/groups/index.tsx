import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, TextField } from '@/components/Form';
import {
  groupKeys,
  listMyGroups,
  listMyInvitations,
  previewInvitation,
  redeemInvitation,
  respondToInvitation,
  tokenFrom,
  type InvitationPreview,
} from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-090 Groups: my groups, invitations to answer, join with a link, create (premium). */
export default function GroupsScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const premium = useSessionStore(
    (state) => state.me?.entitlements?.features?.['groups.create'] ?? false,
  );
  const [code, setCode] = useState('');
  const [preview, setPreview] = useState<InvitationPreview | null>(null);

  const groups = useQuery({
    queryKey: groupKeys.mine,
    queryFn: () => listMyGroups(getApiClient()),
  });
  const invitations = useQuery({
    queryKey: groupKeys.invitations,
    queryFn: () => listMyInvitations(getApiClient()),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['groups'] });
  const respond = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) =>
      respondToInvitation(getApiClient(), id, accept),
    onSuccess: refresh,
  });
  const look = useMutation({
    mutationFn: () => previewInvitation(getApiClient(), tokenFrom(code)),
    onSuccess: setPreview,
  });
  const join = useMutation({
    mutationFn: () => redeemInvitation(getApiClient(), tokenFrom(code)),
    onSuccess: (member) => {
      setCode('');
      setPreview(null);
      refresh();
      router.push({ pathname: '/groups/[id]', params: { id: member.group_id } });
    },
  });
  const joinError = [look.error, join.error].find(Boolean);
  const joinMessage =
    joinError instanceof ApiProblem && joinError.code === 'group_capacity_reached'
      ? t('groups.full')
      : joinError
        ? t('groups.invalidInvite')
        : null;

  const heading = (text: string) => (
    <Text
      accessibilityRole="header"
      style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
    >
      {text}
    </Text>
  );

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('groups.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {(invitations.data?.data ?? []).length > 0 ? heading(t('groups.invitations')) : null}
        {(invitations.data?.data ?? []).map((invitation) => (
          <View
            key={invitation.id}
            style={[styles.card, { borderColor: theme.colors.divider }]}
            testID={`invitation-${invitation.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {invitation.group.name}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('groups.invitedBy', { name: invitation.created_by?.display_name ?? '—' })}
            </Text>
            <View style={styles.actions}>
              <View style={styles.fill}>
                <Button
                  label={t('groups.accept')}
                  onPress={() => respond.mutate({ id: invitation.id, accept: true })}
                  testID={`invitation-accept-${invitation.id}`}
                />
              </View>
              <View style={styles.fill}>
                <Button
                  label={t('groups.decline')}
                  variant="secondary"
                  onPress={() => respond.mutate({ id: invitation.id, accept: false })}
                  testID={`invitation-decline-${invitation.id}`}
                />
              </View>
            </View>
          </View>
        ))}

        {heading(t('groups.mine'))}
        {(groups.data?.data ?? []).length === 0 && groups.isSuccess ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="groups-empty"
          >
            {t('groups.empty')}
          </Text>
        ) : null}
        {(groups.data?.data ?? []).map((group) => (
          <Pressable
            key={group.id}
            onPress={() => router.push({ pathname: '/groups/[id]', params: { id: group.id } })}
            accessibilityRole="button"
            style={[styles.card, { borderColor: theme.colors.divider }]}
            testID={`group-${group.id}`}
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {group.name}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('groups.summary', {
                place: group.primary_destination.name,
                count: group.member_count,
              })}
            </Text>
          </Pressable>
        ))}

        {heading(t('groups.joinTitle'))}
        <TextField
          label={t('groups.joinCode')}
          value={code}
          onChangeText={(value) => {
            setCode(value);
            setPreview(null);
          }}
          autoCapitalize="none"
          autoCorrect={false}
          testID="groups-join-code"
        />
        {preview ? (
          <View
            style={[styles.card, { borderColor: theme.colors.divider }]}
            testID="groups-preview"
          >
            <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
              {preview.group.name}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('groups.summary', {
                place: preview.group.primary_destination.name,
                count: preview.group.member_count,
              })}
            </Text>
            <Button
              label={preview.is_member ? t('groups.open') : t('groups.join')}
              onPress={() => join.mutate()}
              busy={join.isPending}
              testID="groups-join"
            />
          </View>
        ) : (
          <Button
            label={t('groups.check')}
            variant="secondary"
            onPress={() => look.mutate()}
            disabled={tokenFrom(code).length < 32}
            busy={look.isPending}
            testID="groups-check"
          />
        )}
        {joinMessage ? <Notice tone="error">{joinMessage}</Notice> : null}

        {premium ? (
          <Button
            label={t('groups.create')}
            onPress={() => router.push('/groups/new')}
            testID="groups-create"
          />
        ) : (
          <>
            <Notice tone="info" testID="groups-premium-note">
              {t('groups.premiumNote')}
            </Notice>
            {/* Free travellers can't reach the create screen, so the way to Premium starts here. */}
            <Button
              label={t('paywall.seePremium')}
              variant="secondary"
              icon="diamond-outline"
              onPress={() =>
                router.push({ pathname: '/paywall', params: { reason: 'groups.create' } })
              }
              testID="groups-see-premium"
            />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 6 },
  actions: { flexDirection: 'row', gap: 8 },
});
