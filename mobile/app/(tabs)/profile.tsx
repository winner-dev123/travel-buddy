import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { signOut } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { Button, Notice } from '@/components/Form';
import { MenuRow } from '@/components/MenuRow';
import { accountKeys, cancelDeletion, unreadCount } from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import type { UserSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-100 Profile (Phase 1 slice): account, display name, privacy summary, sign out. */
export default function ProfileScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const status = useSessionStore((state) => state.status);
  const me = useSessionStore((state) => state.me);

  if (status === 'restoring') {
    return (
      <SafeAreaView style={[styles.center, { backgroundColor: theme.colors.background }]}>
        <ActivityIndicator color={theme.colors.primary} />
      </SafeAreaView>
    );
  }

  if (status !== 'signed_in' || !me) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <View
          style={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
          testID="profile-signed-out"
        >
          <Text
            accessibilityRole="header"
            style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
          >
            {t('account.signedOutTitle')}
          </Text>
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('account.signedOutBody')}
          </Text>
          <Button
            label={t('account.goToSignIn')}
            onPress={() => router.push('/sign-in')}
            testID="profile-go-to-sign-in"
          />
        </View>
      </SafeAreaView>
    );
  }

  return <SignedInProfile me={me} />;
}

function SignedInProfile({ me }: { me: Me }) {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unread = useQuery({
    queryKey: accountKeys.unread,
    queryFn: () => unreadCount(getApiClient()),
  });
  const restrictions = me.account.restrictions ?? [];
  const pending = me.account.status === 'pending_deletion';

  async function undoDeletion(): Promise<void> {
    setError(null);
    setCancelling(true);
    try {
      await cancelDeletion(getApiClient());
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setCancelling(false);
    }
  }

  const date = (iso: string) => new Date(iso).toLocaleDateString(i18n.language);

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
        testID="profile-signed-in"
      >
        <View style={styles.header}>
          <Avatar
            user={{
              id: me.profile.id,
              handle: me.profile.handle,
              display_name: me.profile.display_name,
              avatar: (me.profile.avatar as UserSummary['avatar']) ?? null,
            }}
            size={64}
          />
          <View style={styles.fill}>
            <Text
              accessibilityRole="header"
              style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
              testID="profile-display-name"
            >
              {me.profile.display_name}
            </Text>
            <Text
              style={[theme.typography.body, { color: theme.colors.textSecondary }]}
              testID="profile-handle"
            >
              @{me.profile.handle}
              {me.profile.account_visibility === 'private' ? ` · ${t('account.private')}` : ''}
            </Text>
          </View>
        </View>
        {me.profile.bio ? (
          <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
            {me.profile.bio}
          </Text>
        ) : null}
        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          testID="profile-email"
        >
          {`${me.account.email ?? '—'} · ${
            me.account.email_verified ? t('account.verified') : t('account.notVerified')
          }`}
        </Text>
        {pending ? (
          <View style={{ gap: theme.spacing[2] }} testID="profile-deletion-pending">
            <Notice tone="error">
              {t('account.deletionPending', {
                date: me.account.deletion_scheduled_for
                  ? date(me.account.deletion_scheduled_for)
                  : '—',
              })}
            </Notice>
            <Button
              label={t('account.cancelDeletion')}
              onPress={() => void undoDeletion()}
              busy={cancelling}
              testID="profile-cancel-deletion"
            />
          </View>
        ) : null}
        {restrictions.map((restriction) => (
          <Notice
            tone="info"
            key={restriction.kind}
            testID={`profile-restriction-${restriction.kind}`}
          >
            {restriction.until
              ? t('account.restrictionUntil', {
                  what: t(`account.restrictions.${restriction.kind}`),
                  date: date(restriction.until),
                })
              : t('account.restriction', { what: t(`account.restrictions.${restriction.kind}`) })}
          </Notice>
        ))}
        {error ? <Notice tone="error">{error}</Notice> : null}
        <View>
          <MenuRow
            icon="notifications-outline"
            label={t('notifications.title')}
            detail={unread.data ? String(unread.data) : undefined}
            onPress={() => router.push('/notifications')}
            testID="profile-menu-notifications"
          />
          <MenuRow
            icon="person-outline"
            label={t('account.editProfile')}
            onPress={() => router.push('/settings/profile')}
            testID="profile-menu-edit"
          />
          <MenuRow
            icon="lock-closed-outline"
            label={t('account.privacyHeading')}
            onPress={() => router.push('/settings/privacy')}
            testID="profile-menu-privacy"
          />
          <MenuRow
            icon="bookmark-outline"
            label={t('saved.title')}
            onPress={() => router.push('/saved')}
            testID="profile-menu-saved"
          />
          <MenuRow
            icon="albums-outline"
            label={t('bookmarks.title')}
            onPress={() => router.push('/bookmarks')}
            testID="profile-menu-bookmarks"
          />
          <MenuRow
            icon="shield-outline"
            label={t('safetyCenter.title')}
            onPress={() => router.push('/settings/safety')}
            testID="profile-menu-safety"
          />
          <MenuRow
            icon="options-outline"
            label={t('notificationSettings.title')}
            onPress={() => router.push('/settings/notifications')}
            testID="profile-menu-notification-settings"
          />
          <MenuRow
            icon="language-outline"
            label={t('languageSettings.title')}
            onPress={() => router.push('/settings/language')}
            testID="profile-menu-language"
          />
          <MenuRow
            icon="phone-portrait-outline"
            label={t('sessions.title')}
            onPress={() => router.push('/settings/sessions')}
            testID="profile-menu-sessions"
          />
          <MenuRow
            icon="star-outline"
            label={t('subscription.title')}
            onPress={() => router.push('/settings/subscription')}
            testID="profile-menu-subscription"
          />
          <MenuRow
            icon="ban-outline"
            label={t('account.blocked')}
            onPress={() => router.push('/settings/blocked')}
            testID="profile-menu-blocked"
          />
          <MenuRow
            icon="gift-outline"
            label={t('challenges.myRewards')}
            onPress={() => router.push('/rewards')}
            testID="profile-menu-rewards"
          />
          <MenuRow
            icon="download-outline"
            label={t('account.yourData')}
            onPress={() => router.push('/settings/data')}
            testID="profile-menu-data"
          />
          <MenuRow
            icon="help-buoy-outline"
            label={t('help.title')}
            onPress={() => router.push('/settings/help')}
            testID="profile-menu-help"
          />
          {!pending ? (
            <MenuRow
              icon="trash-outline"
              label={t('account.deleteAccount')}
              destructive
              onPress={() => router.push('/settings/delete-account')}
              testID="profile-menu-delete"
            />
          ) : null}
        </View>
        <Button
          variant="secondary"
          label={t('account.signOut')}
          onPress={() => void signOut(getApiClient())}
          testID="profile-sign-out"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: { flexDirection: 'row', alignItems: 'center', gap: 16 },
});
