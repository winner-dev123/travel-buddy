import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import { Avatar } from '@/features/feed/PostCard';
import {
  answerTransfer,
  createInviteLink,
  getGroup,
  groupKeys,
  leaveGroup,
  listMembers,
  postAnnouncement,
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
  const meId = useSessionStore((state) => state.me?.account.id);
  const answer = useMutation({
    mutationFn: ({
      transferId,
      action,
    }: {
      transferId: string;
      action: 'accept' | 'decline' | 'cancel';
    }) => answerTransfer(getApiClient(), id, transferId, action),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: groupKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: groupKeys.members(id) });
    },
  });
  const [announcement, setAnnouncement] = useState<string | null>(null);
  const [pinIt, setPinIt] = useState(true);
  const announcementKey = useRef(getApiClient().newIdempotencyKey());
  const announce = useMutation({
    mutationFn: () =>
      postAnnouncement(
        getApiClient(),
        id,
        announcementKey.current,
        (announcement ?? '').trim(),
        pinIt,
      ),
    onSuccess: () => {
      setAnnouncement(null);
      announcementKey.current = getApiClient().newIdempotencyKey();
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
  const canManage = ['group.edit', 'roles.assign', 'members.remove'].some((p) =>
    permissions.includes(p),
  );
  const pending = data.pending_transfer ?? null;
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
        {pending && pending.to_user.id === meId ? (
          <View style={{ gap: theme.spacing[2] }} testID="group-transfer-offer">
            <Notice tone="info">
              {t('manageGroup.offerReceived', { name: pending.from_user.display_name })}
            </Notice>
            <View style={styles.row}>
              <View style={styles.fill}>
                <Button
                  label={t('manageGroup.accept')}
                  onPress={() => answer.mutate({ transferId: pending.id, action: 'accept' })}
                  busy={answer.isPending}
                  testID="group-transfer-accept"
                />
              </View>
              <View style={styles.fill}>
                <Button
                  label={t('manageGroup.decline')}
                  variant="secondary"
                  onPress={() => answer.mutate({ transferId: pending.id, action: 'decline' })}
                  testID="group-transfer-decline"
                />
              </View>
            </View>
          </View>
        ) : null}
        {pending && pending.from_user.id === meId ? (
          <View style={{ gap: theme.spacing[2] }} testID="group-transfer-sent">
            <Notice tone="info">
              {t('manageGroup.offerPending', { name: pending.to_user.display_name })}
            </Notice>
            <Button
              label={t('manageGroup.cancelOffer')}
              variant="secondary"
              onPress={() => answer.mutate({ transferId: pending.id, action: 'cancel' })}
              testID="group-transfer-cancel"
            />
          </View>
        ) : null}
        {answer.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        {permissions.includes('announcements.post') && data.status === 'active' ? (
          announcement === null ? (
            <Button
              label={t('groups.announce')}
              variant="secondary"
              onPress={() => setAnnouncement('')}
              testID="group-announce"
            />
          ) : (
            <View style={{ gap: theme.spacing[2] }} testID="group-announce-form">
              <TextField
                label={t('groups.announcement')}
                value={announcement}
                onChangeText={setAnnouncement}
                multiline
                maxLength={4000}
                testID="group-announce-body"
              />
              <SwitchRow
                label={t('groups.pinAnnouncement')}
                value={pinIt}
                onValueChange={setPinIt}
                testID="group-announce-pin"
              />
              {announce.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
              <Button
                label={t('groups.sendAnnouncement')}
                onPress={() => announce.mutate()}
                disabled={announcement.trim().length === 0}
                busy={announce.isPending}
                testID="group-announce-send"
              />
              <Button
                label={t('common.cancel')}
                variant="secondary"
                onPress={() => setAnnouncement(null)}
                testID="group-announce-cancel"
              />
            </View>
          )
        ) : null}
        {announce.isSuccess && announcement === null ? (
          <Notice tone="success" testID="group-announce-sent">
            {t('groups.announcementSent')}
          </Notice>
        ) : null}
        {canManage && data.status === 'active' ? (
          <Button
            label={t('manageGroup.title')}
            variant="secondary"
            onPress={() => router.push({ pathname: '/groups/manage', params: { id: data.id } })}
            testID="group-manage"
          />
        ) : null}
        <Button
          label={t('groups.challenges')}
          variant="secondary"
          onPress={() => router.push({ pathname: '/challenges', params: { groupId: data.id } })}
          testID="group-challenges"
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
