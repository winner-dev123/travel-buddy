import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import { Button, Notice } from '@/components/Form';
import {
  exploreKeys,
  getPlace,
  listSavedPlaces,
  savePlace,
  unsavePlace,
} from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

const SHOWN_ATTRIBUTES = ['opening_hours', 'website', 'phone', 'cuisine', 'wheelchair'] as const;

/** SCR-041 Place detail: licensed data with its source and freshness (DEST-003), save. */
export default function PlaceScreen() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');

  const place = useQuery({
    queryKey: exploreKeys.place(id),
    queryFn: () => getPlace(getApiClient(), id),
  });
  const saved = useQuery({
    queryKey: exploreKeys.saved,
    queryFn: () => listSavedPlaces(getApiClient()),
    enabled: signedIn,
  });
  const isSaved = (saved.data ?? []).some((entry) => entry.place.id === id);
  const toggle = useMutation({
    mutationFn: () =>
      isSaved
        ? unsavePlace(getApiClient(), id)
        : savePlace(getApiClient(), id).then(() => undefined),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: exploreKeys.saved }),
  });

  const data = place.data;
  const text = (value: string, strong = false) => (
    <Text
      style={[
        strong ? theme.typography.bodyStrong : theme.typography.body,
        { color: theme.colors.textPrimary },
      ]}
    >
      {value}
    </Text>
  );

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: data?.name ?? t('explore.place') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {place.isError ? <Notice tone="error">{t('explore.placeMissing')}</Notice> : null}
        {data ? (
          <>
            <Text
              accessibilityRole="header"
              style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
            >
              {data.name}
            </Text>
            <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
              {t(`explore.categories.${data.category}`)}
            </Text>
            {data.status === 'closed_permanently' ? (
              <Notice tone="error">{t('explore.closed')}</Notice>
            ) : null}
            {data.address
              ? text(
                  [data.address.line1, data.address.locality, data.address.postal_code]
                    .filter(Boolean)
                    .join(', '),
                )
              : null}
            <View style={{ gap: theme.spacing[1] }} testID="place-attributes">
              {SHOWN_ATTRIBUTES.filter((key) => typeof data.attributes[key] === 'string').map(
                (key) => (
                  <Text
                    key={key}
                    style={[theme.typography.body, { color: theme.colors.textPrimary }]}
                  >
                    {t(`explore.attributes.${key}`)}: {String(data.attributes[key])}
                  </Text>
                ),
              )}
            </View>
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('explore.freshness', {
                date: new Date(data.data_freshness_at).toLocaleDateString(i18n.language),
              })}
            </Text>
            {data.data_stale ? <Notice tone="info">{t('explore.stale')}</Notice> : null}
            <Text
              style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
              testID="place-attribution"
            >
              {t('explore.source', { source: data.attribution.text })}
            </Text>
            {signedIn ? (
              <Button
                label={isSaved ? t('explore.unsave') : t('explore.save')}
                variant={isSaved ? 'secondary' : 'primary'}
                onPress={() => toggle.mutate()}
                busy={toggle.isPending}
                disabled={saved.isLoading}
                testID="place-save"
              />
            ) : null}
            {toggle.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
