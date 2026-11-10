import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { exploreKeys, listSavedPlaces, unsavePlace } from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-102 Saved places: what I bookmarked while exploring, newest first, grouped by
 * collection; open a place or remove it. */
export default function SavedPlacesScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const saved = useQuery({
    queryKey: exploreKeys.saved,
    queryFn: () => listSavedPlaces(getApiClient()),
  });
  const remove = useMutation({
    mutationFn: (placeId: string) => unsavePlace(getApiClient(), placeId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: exploreKeys.saved }),
  });
  const items = saved.data ?? [];
  const collections = [...new Set(items.map((entry) => entry.collection))];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('saved.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {saved.isPending ? <ActivityIndicator /> : null}
        {saved.isError ? (
          <Notice tone="error" testID="saved-error">
            {t('saved.error')}
          </Notice>
        ) : null}
        {remove.isError ? <Notice tone="error">{t('user.actionFailed')}</Notice> : null}
        {saved.isSuccess && items.length === 0 ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="saved-empty"
          >
            {t('saved.empty')}
          </Text>
        ) : null}
        {collections.map((collection) => (
          <View key={collection} style={{ gap: theme.spacing[1] }}>
            {collections.length > 1 || collection !== 'default' ? (
              <Text
                accessibilityRole="header"
                style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
              >
                {collection === 'default' ? t('saved.defaultCollection') : collection}
              </Text>
            ) : null}
            {items
              .filter((entry) => entry.collection === collection)
              .map((entry) => (
                <View
                  key={entry.place.id}
                  style={[styles.row, { borderBottomColor: theme.colors.divider }]}
                >
                  <Pressable
                    onPress={() =>
                      router.push({ pathname: '/places/[id]', params: { id: entry.place.id } })
                    }
                    accessibilityRole="link"
                    style={styles.fill}
                    testID={`saved-${entry.place.id}`}
                  >
                    <Text
                      style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}
                    >
                      {entry.place.name}
                    </Text>
                    <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                      {[t(`explore.categories.${entry.place.category}`), entry.note]
                        .filter(Boolean)
                        .join(' · ')}
                    </Text>
                  </Pressable>
                  <Pressable
                    onPress={() => remove.mutate(entry.place.id)}
                    accessibilityRole="button"
                    accessibilityLabel={t('saved.removeA11y', { name: entry.place.name })}
                    hitSlop={8}
                    testID={`saved-remove-${entry.place.id}`}
                  >
                    <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
                      {t('saved.remove')}
                    </Text>
                  </Pressable>
                </View>
              ))}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: 10,
  },
});
