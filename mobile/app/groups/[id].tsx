import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice } from '@/components/Form';
import { Avatar } from '@/features/feed/PostCard';
import {
  createInviteLink,
  getGroup,
  groupKeys,
  leaveGroup,
  listMembers,
} from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-091 Group: details, members, the group chat, invite links (admins), leave. */
export default function GroupScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const group = useQuery({
    queryKey: groupKeys.detail(id),
    queryFn: () => getGroup(getApiClient(), id),
  });
  const members = useQuery({
    queryKey: groupKeys.members(id),
    queryFn: () => listMembers(getApiClient(), id),
  });
  const invite = useMutation({
    mutationFn: () => createInviteLink(getApiClient(), id),
    onSuccess: async (created) => {
      if (created.url) {
        await Share.share({ message: t('groups.shareMessage', { url: created.url }) });
      }
    },
  });
  const leave = useMutation({
    mutationFn: () => leaveGroup(getApiClient(), id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['groups'] });
      router.back();
    },
  });

  if (group.isPending) {
    return <ActivityIndicator color={theme.colors.primary} style={styles.loading} />;
  }
  if (group.isError || !group.data) {
    return <Notice tone="error">{t('groups.notFound')}</Notice>;
  }
  const data = group.data;
  const permissions = data.my_membership?.permissions ?? [];
  const canInvite = permissions.includes('members.invite');
  const isOwner = data.my_membership?.role === 'owner';
  const inviteError =
    invite.error instanceof ApiProblem && invite.error.code === 'entitlement_required'
      ? t('groups.inviteLapsed')
      : invite.isError
        ? t('user.actionFailed')
        : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: data.name }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        <Text style={[theme.typography.title2, { color: theme.colors.textPrimary }]}>
          {data.name}
        </Text>
        <Text
          style={[theme.typography.body, { color: theme.colors.textSecondary }]}
          testID="group-summary"
        >
          {t('groups.summary', { place: data.primary_destination.name, count: data.member_count })}
        </Text>
        {data.description ? (
          <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
            {data.description}
          </Text>
        ) : null}
        {data.status === 'archived' ? <Notice tone="info">{t('groups.archived')}</Notice> : null}
        {data.my_membership?.status === 'restricted' ? (
          <Notice tone="info" testID="group-restricted">
            {t('groups.restricted')}
          </Notice>
        ) : null}
        <Button
          label={t('groups.openChat')}
          onPress={() =>
            router.push({ pathname: '/chat/[id]', params: { id: data.conversation_id } })
          }
          testID="group-open-chat"
        />
        {canInvite && data.status === 'active' ? (
          <Button
            label={t('groups.inviteLink')}
            variant="secondary"
            onPress={() => invite.mutate()}
            busy={invite.isPending}
            testID="group-invite"
          />
        ) : null}
        {inviteError ? <Notice tone="error">{inviteError}</Notice> : null}

        <Text
          accessibilityRole="header"
          style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
        >
          {t('groups.members')}
        </Text>
        {(members.data?.data ?? []).map((member) => (
          <View key={member.user.id} style={styles.row} testID={`member-${member.user.id}`}>
            <Avatar user={member.user} size={32} />
            <Text style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}>
              {member.user.display_name}
            </Text>
            {member.role !== 'member' ? (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t(`groups.roles.${member.role}`)}
              </Text>
            ) : null}
          </View>
        ))}

        {isOwner ? (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('groups.ownerCantLeave')}
          </Text>
        ) : (
          <Button
            label={t('groups.leave')}
            variant="secondary"
            onPress={() => leave.mutate()}
            busy={leave.isPending}
            testID="group-leave"
          />
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  loading: { marginTop: 32 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
});
