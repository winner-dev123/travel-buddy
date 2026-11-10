import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as Linking from 'expo-linking';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice } from '@/components/Form';
import { previewInvitation, redeemInvitation, tokenFrom } from '@/features/groups/api';
import { useAppTheme } from '@/theme/useAppTheme';

const TOKEN = /^[A-Za-z0-9_-]{32,}$/;

/**
 * SCR-073 Invitation landing (GRP-005): opened by `travelbuddy://invite#t=<token>`, the app form
 * of the web invitation link. The token stays in the fragment, never in a request URL; it is
 * sent only in POST bodies. Shows the group and joins it.
 */
export default function InviteScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const url = Linking.useLinkingURL();
  const params = useLocalSearchParams<{ t?: string }>();
  const candidate = params.t ?? (url ? tokenFrom(url) : '');
  const token = TOKEN.test(candidate) ? candidate : null;
  const status = useSessionStore((state) => state.status);
  const signedOut = status === 'signed_out';

  const preview = useQuery({
    queryKey: ['groups', 'invite-preview', token],
    queryFn: () => previewInvitation(getApiClient(), token as string),
    enabled: token !== null && status === 'signed_in',
    retry: false,
    gcTime: 0,
  });
  const join = useMutation({
    mutationFn: () => redeemInvitation(getApiClient(), token as string),
    onSuccess: (member) => {
      void queryClient.invalidateQueries({ queryKey: ['groups'] });
      router.replace({ pathname: '/groups/[id]', params: { id: member.group_id } });
    },
  });

  const failure = preview.error ?? join.error;
  const message =
    token === null
      ? t('groups.invalidInvite')
      : failure instanceof ApiProblem && failure.code === 'group_capacity_reached'
        ? t('groups.full')
        : failure
          ? t('groups.invalidInvite')
          : null;
  const group = preview.data?.group;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('groups.inviteTitle') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {preview.isLoading ? <ActivityIndicator color={theme.colors.primary} /> : null}
        {message ? (
          <Notice tone="error" testID="invite-invalid">
            {message}
          </Notice>
        ) : null}
        {signedOut && token ? (
          <>
            <Notice tone="info" testID="invite-sign-in-note">
              {t('groups.inviteSignIn')}
            </Notice>
            <Button
              label={t('account.goToSignIn')}
              onPress={() => {
                // Back to this invitation once signed in (an existing account).
                useSessionStore.getState().setPendingInvite(token);
                router.push('/sign-in');
              }}
              testID="invite-sign-in"
            />
          </>
        ) : null}
        {group && preview.data ? (
          <View
            style={[styles.card, { borderColor: theme.colors.divider }]}
            testID="invite-preview"
          >
            <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
              {group.name}
            </Text>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('groups.summary', {
                place: group.primary_destination.name,
                count: group.member_count,
              })}
            </Text>
            {preview.data.inviter ? (
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                {t('groups.invitedBy', { name: preview.data.inviter.display_name })}
              </Text>
            ) : null}
            <Button
              label={preview.data.is_member ? t('groups.open') : t('groups.join')}
              onPress={() =>
                preview.data.is_member
                  ? router.replace({ pathname: '/groups/[id]', params: { id: group.id } })
                  : join.mutate()
              }
              busy={join.isPending}
              testID="invite-join"
            />
          </View>
        ) : null}
        <Button
          label={t('groups.notNow')}
          variant="secondary"
          onPress={() => router.replace('/')}
          testID="invite-dismiss"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 12, padding: 16, gap: 8 },
});
