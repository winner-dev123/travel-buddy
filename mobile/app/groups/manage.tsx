import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { showActions } from '@/components/ActionSheet';
import { Notice, SwitchRow } from '@/components/Form';
import { Avatar } from '@/features/feed/PostCard';
import {
  archiveGroup,
  type AssignableRole,
  changeMemberRole,
  getGroup,
  getGroupSettings,
  groupKeys,
  type GroupMember,
  liftRestriction,
  type GroupSettings,
  listGroupInvitations,
  listMembers,
  offerTransfer,
  removeMember,
  restrictMember,
  revokeInvitation,
  ROLE_RANK,
  updateGroupSettings,
} from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

const ROLES: AssignableRole[] = ['admin', 'moderator', 'member'];
const RESTRICT_FOR = [
  { hours: 1, label: 'manageGroup.restrictFor.1' },
  { hours: 24, label: 'manageGroup.restrictFor.24' },
  { hours: 168, label: 'manageGroup.restrictFor.168' },
] as const;

/** SCR-072 Manage group: chat and invitation settings, member roles, removal, and offering
 * ownership to another member (GRP-005..009). Each control shows only with its permission;
 * removing members never depends on the owner's subscription. */
export default function ManageGroupScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const group = useQuery({
    queryKey: groupKeys.detail(id),
    queryFn: () => getGroup(getApiClient(), id),
  });
  const members = useQuery({
    queryKey: groupKeys.members(id),
    queryFn: () => listMembers(getApiClient(), id),
  });
  const permissions = group.data?.my_membership?.permissions ?? [];
  const canEdit = permissions.includes('group.edit');
  const settings = useQuery({
    queryKey: groupKeys.settings(id),
    queryFn: () => getGroupSettings(getApiClient(), id),
    enabled: canEdit,
  });
  const canInvite = permissions.includes('members.invite');
  const invitations = useQuery({
    queryKey: groupKeys.sentInvitations(id),
    queryFn: () => listGroupInvitations(getApiClient(), id),
    enabled: canInvite,
  });
  const revoke = useMutation({
    mutationFn: (invitationId: string) => revokeInvitation(getApiClient(), id, invitationId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: groupKeys.sentInvitations(id) }),
  });
  const archive = useMutation({
    mutationFn: () => archiveGroup(getApiClient(), id),
    onSuccess: (archived) => {
      queryClient.setQueryData(groupKeys.detail(id), archived);
      void queryClient.invalidateQueries({ queryKey: groupKeys.mine });
    },
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: groupKeys.members(id) });
    void queryClient.invalidateQueries({ queryKey: groupKeys.detail(id) });
  };
  const saveSettings = useMutation({
    mutationFn: (changes: Partial<Omit<GroupSettings, 'version'>>) =>
      updateGroupSettings(getApiClient(), id, settings.data?.version ?? 1, changes),
    onSuccess: (saved) => queryClient.setQueryData(groupKeys.settings(id), saved),
    onError: () => void queryClient.invalidateQueries({ queryKey: groupKeys.settings(id) }),
  });
  const role = useMutation({
    mutationFn: ({ userId, value }: { userId: string; value: AssignableRole }) =>
      changeMemberRole(getApiClient(), id, userId, value),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removeMember(getApiClient(), id, userId),
    onSuccess: refresh,
  });
  const restrict = useMutation({
    mutationFn: async ({ userId, hours }: { userId: string; hours: number | null }) => {
      if (hours === null) await liftRestriction(getApiClient(), id, userId);
      else
        await restrictMember(getApiClient(), id, userId, new Date(Date.now() + hours * 3_600_000));
    },
    onSuccess: refresh,
  });
  const transfer = useMutation({
    mutationFn: (userId: string) => offerTransfer(getApiClient(), id, userId),
    onSuccess: refresh,
  });

  if (group.isPending) return <ActivityIndicator style={styles.loading} />;
  if (!group.data) return <Notice tone="error">{t('groups.notFound')}</Notice>;
  const myRole = group.data.my_membership?.role ?? 'member';
  const myRank = ROLE_RANK[myRole];
  const canAssign = permissions.includes('roles.assign');
  const canRemove = permissions.includes('members.remove');
  const canTransfer = permissions.includes('group.transfer');
  const canRestrict = permissions.includes('members.restrict');
  const failed = [saveSettings, role, remove, restrict, transfer, revoke, archive].find(
    (m) => m.isError,
  )?.error;
  const error =
    failed instanceof ApiProblem && failed.code === 'precondition_failed'
      ? t('manageGroup.stale')
      : failed
        ? t('user.actionFailed')
        : null;
  const below = (member: GroupMember) => ROLE_RANK[member.role] < myRank;

  const confirmRemove = (member: GroupMember) =>
    Alert.alert(
      t('manageGroup.removeTitle', { name: member.user.display_name }),
      t('manageGroup.removeBody'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        {
          text: t('manageGroup.remove'),
          style: 'destructive',
          onPress: () => remove.mutate(member.user.id),
        },
      ],
    );
  const chooseRestriction = (member: GroupMember) =>
    showActions(
      t('manageGroup.restrictTitle', { name: member.user.display_name }),
      t('manageGroup.restrictBody'),
      [
        ...RESTRICT_FOR.map(({ hours, label }) => ({
          text: t(label),
          onPress: () => restrict.mutate({ userId: member.user.id, hours }),
        })),
        { text: t('common.cancel'), style: 'cancel' as const },
      ],
    );
  const confirmArchive = () =>
    Alert.alert(t('manageGroup.archiveTitle'), t('manageGroup.archiveBody'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('manageGroup.archive'), style: 'destructive', onPress: () => archive.mutate() },
    ]);
  const confirmTransfer = (member: GroupMember) =>
    Alert.alert(
      t('manageGroup.transferTitle', { name: member.user.display_name }),
      t('manageGroup.transferBody'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        { text: t('manageGroup.transfer'), onPress: () => transfer.mutate(member.user.id) },
      ],
    );
  const chip = (selected: boolean) => [
    styles.chip,
    {
      borderColor: selected ? theme.colors.primary : theme.colors.divider,
      backgroundColor: selected ? theme.colors.primary : 'transparent',
    },
  ];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('manageGroup.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {error ? (
          <Notice tone="error" testID="manage-error">
            {error}
          </Notice>
        ) : null}
        {transfer.isSuccess ? (
          <Notice tone="success" testID="manage-transfer-sent">
            {t('manageGroup.transferSent', { name: transfer.data.to_user.display_name })}
          </Notice>
        ) : null}
        {canEdit && settings.data ? (
          <View style={{ gap: theme.spacing[2] }} testID="manage-settings">
            <Text
              accessibilityRole="header"
              style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
            >
              {t('manageGroup.settings')}
            </Text>
            <SwitchRow
              label={t('manageGroup.membersCanInvite')}
              value={settings.data.members_can_invite}
              onValueChange={(value) => saveSettings.mutate({ members_can_invite: value })}
              testID="setting-members-invite"
            />
            <SwitchRow
              label={t('manageGroup.adminsOnly')}
              value={settings.data.chat_mode === 'admins_only'}
              onValueChange={(value) =>
                saveSettings.mutate({ chat_mode: value ? 'admins_only' : 'everyone' })
              }
              testID="setting-admins-only"
            />
            <SwitchRow
              label={t('manageGroup.fullHistory')}
              value={settings.data.new_member_history === 'full'}
              onValueChange={(value) =>
                saveSettings.mutate({ new_member_history: value ? 'full' : 'from_join' })
              }
              testID="setting-full-history"
            />
          </View>
        ) : null}
        <Text
          accessibilityRole="header"
          style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
        >
          {t('groups.members')}
        </Text>
        {(members.data?.data ?? []).map((member) => (
          <View
            key={member.user.id}
            style={[styles.member, { borderBottomColor: theme.colors.divider }]}
            testID={`manage-member-${member.user.id}`}
          >
            <View style={styles.row}>
              <Avatar user={member.user} size={32} />
              <Text
                style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}
              >
                {member.user.display_name}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t(`groups.roles.${member.role}`)}
              </Text>
            </View>
            {member.status === 'restricted' && member.restricted_until ? (
              <Text
                style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
                testID={`restricted-until-${member.user.id}`}
              >
                {t('manageGroup.restrictedUntil', {
                  time: new Date(member.restricted_until).toLocaleString(i18n.language, {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  }),
                })}
              </Text>
            ) : null}
            {below(member) ? (
              <View style={styles.actions}>
                {canAssign
                  ? ROLES.filter((value) => ROLE_RANK[value] < myRank).map((value) => (
                      <Pressable
                        key={value}
                        onPress={() =>
                          member.role !== value && role.mutate({ userId: member.user.id, value })
                        }
                        accessibilityRole="radio"
                        accessibilityState={{ selected: member.role === value }}
                        style={chip(member.role === value)}
                        testID={`role-${member.user.id}-${value}`}
                      >
                        <Text
                          style={[
                            theme.typography.label,
                            {
                              color:
                                member.role === value
                                  ? theme.colors.onPrimary
                                  : theme.colors.textPrimary,
                            },
                          ]}
                        >
                          {t(`groups.roles.${value}`)}
                        </Text>
                      </Pressable>
                    ))
                  : null}
                {canTransfer ? (
                  <Pressable
                    onPress={() => confirmTransfer(member)}
                    accessibilityRole="button"
                    testID={`transfer-${member.user.id}`}
                  >
                    <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                      {t('manageGroup.makeOwner')}
                    </Text>
                  </Pressable>
                ) : null}
                {canRestrict ? (
                  member.status === 'restricted' ? (
                    <Pressable
                      onPress={() => restrict.mutate({ userId: member.user.id, hours: null })}
                      accessibilityRole="button"
                      testID={`lift-${member.user.id}`}
                    >
                      <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                        {t('manageGroup.lift')}
                      </Text>
                    </Pressable>
                  ) : (
                    <Pressable
                      onPress={() => chooseRestriction(member)}
                      accessibilityRole="button"
                      testID={`restrict-${member.user.id}`}
                    >
                      <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
                        {t('manageGroup.restrict')}
                      </Text>
                    </Pressable>
                  )
                ) : null}
                {canRemove ? (
                  <Pressable
                    onPress={() => confirmRemove(member)}
                    accessibilityRole="button"
                    testID={`remove-${member.user.id}`}
                  >
                    <Text style={[theme.typography.label, { color: theme.colors.danger }]}>
                      {t('manageGroup.remove')}
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            ) : null}
          </View>
        ))}
        {canInvite && (invitations.data?.data ?? []).length > 0 ? (
          <View style={{ gap: theme.spacing[2] }} testID="manage-invitations">
            <Text
              accessibilityRole="header"
              style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
            >
              {t('manageGroup.invitations')}
            </Text>
            {(invitations.data?.data ?? []).map((invitation) => (
              <View key={invitation.id} style={styles.row} testID={`invitation-${invitation.id}`}>
                <Text
                  style={[styles.fill, theme.typography.body, { color: theme.colors.textPrimary }]}
                >
                  {invitation.kind === 'direct' && invitation.invitee
                    ? t('manageGroup.invited', { name: invitation.invitee.display_name })
                    : t('manageGroup.link', {
                        used: invitation.use_count ?? 0,
                        max: invitation.max_uses ?? '∞',
                      })}
                </Text>
                <Pressable
                  onPress={() => revoke.mutate(invitation.id)}
                  accessibilityRole="button"
                  testID={`revoke-${invitation.id}`}
                >
                  <Text style={[theme.typography.label, { color: theme.colors.danger }]}>
                    {t('manageGroup.revoke')}
                  </Text>
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}
        {myRole === 'owner' && group.data.status === 'active' ? (
          <Pressable
            onPress={confirmArchive}
            accessibilityRole="button"
            style={styles.archive}
            testID="manage-archive"
          >
            <Text style={[theme.typography.label, { color: theme.colors.danger }]}>
              {t('manageGroup.archive')}
            </Text>
          </Pressable>
        ) : null}
        {group.data.status === 'archived' ? (
          <Notice tone="info" testID="manage-archived">
            {t('manageGroup.archived')}
          </Notice>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  loading: { marginTop: 32 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  member: { gap: 8, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
    paddingLeft: 44,
  },
  chip: { borderWidth: 1, borderRadius: 16, paddingHorizontal: 10, paddingVertical: 4 },
  archive: { paddingVertical: 12 },
});
