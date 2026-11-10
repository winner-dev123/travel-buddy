import { useQuery } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Notice, TextField } from '@/components/Form';
import { searchPeople } from '@/features/account/api';
import { Avatar } from '@/features/feed/PostCard';
import { useAppTheme } from '@/theme/useAppTheme';

/** Find travellers by name or handle (PROF-003). Blocked and deactivated accounts never
 * appear; private accounts show only their summary. */
export default function PeopleSearchScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const q = query.trim();
  const results = useQuery({
    queryKey: ['people', 'search', q],
    queryFn: () => searchPeople(getApiClient(), q),
    enabled: q.length >= 2,
    staleTime: 30_000,
  });
  const people = results.data?.data ?? [];

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('people.title') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <TextField
          label={t('people.search')}
          value={query}
          onChangeText={setQuery}
          autoCapitalize="none"
          autoCorrect={false}
          maxLength={50}
          hint={q.length < 2 ? t('people.hint') : undefined}
          testID="people-query"
        />
        {results.isFetching ? <ActivityIndicator /> : null}
        {results.isError ? (
          <Notice tone="error" testID="people-error">
            {t('people.error')}
          </Notice>
        ) : null}
        {results.isSuccess && people.length === 0 ? (
          <Text
            style={[theme.typography.body, { color: theme.colors.textSecondary }]}
            testID="people-empty"
          >
            {t('people.empty')}
          </Text>
        ) : null}
        {people.map((person) => (
          <Pressable
            key={person.id}
            onPress={() => router.push({ pathname: '/user/[id]', params: { id: person.id } })}
            accessibilityRole="link"
            style={styles.row}
            testID={`people-${person.id}`}
          >
            <Avatar user={person} size={40} />
            <View style={styles.fill}>
              <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
                {person.display_name}
              </Text>
              <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
                @{person.handle}
              </Text>
            </View>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 4 },
});
