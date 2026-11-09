import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { createPost, feedKeys, searchDestinations, type NewPost } from '@/features/feed/api';
import type { DestinationSummary, PostKind } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

const KINDS: PostKind[] = [
  'tip',
  'experience',
  'attraction_recommendation',
  'restaurant_recommendation',
  'text',
];
const LOCATED: ReadonlySet<PostKind> = new Set([
  'attraction_recommendation',
  'restaurant_recommendation',
]);
const VISIBILITIES: NewPost['visibility'][] = ['public', 'followers', 'private'];
const BODY_MAX = 5000;

function Chip({
  label,
  selected,
  onPress,
  testID,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  testID?: string;
}) {
  const theme = useAppTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      style={[
        styles.chip,
        {
          backgroundColor: selected ? theme.colors.primary : theme.colors.surface,
          borderColor: selected ? theme.colors.primary : theme.colors.borderStrong,
        },
      ]}
      testID={testID}
    >
      <Text
        style={[
          theme.typography.label,
          { color: selected ? theme.colors.onPrimary : theme.colors.textPrimary },
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

/** SCR-030 Composer (Phase 1 slice): text stories with an optional destination. */
export default function ComposeScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<PostKind>('tip');
  const [body, setBody] = useState('');
  const [visibility, setVisibility] = useState<NewPost['visibility']>('public');
  const [search, setSearch] = useState('');
  const [destination, setDestination] = useState<DestinationSummary | null>(null);
  // One key for this draft: a retried submit never creates a second post.
  const idempotencyKey = useRef(getApiClient().newIdempotencyKey());

  const matches = useQuery({
    queryKey: ['destinations', 'search', search],
    queryFn: () => searchDestinations(getApiClient(), search),
    enabled: search.trim().length >= 2 && destination === null,
  });
  const publish = useMutation({
    mutationFn: () =>
      createPost(
        getApiClient(),
        { kind, body: body.trim(), visibility, destination },
        idempotencyKey.current,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: feedKeys.all });
      router.back();
    },
  });

  const needsPlace = LOCATED.has(kind) && destination === null;
  const canPublish = body.trim().length > 0 && !needsPlace;
  const errorText =
    publish.error instanceof ApiProblem && publish.error.code === 'email_unverified'
      ? t('compose.verifyEmail')
      : publish.error instanceof ApiProblem && publish.error.code === 'account_restricted'
        ? t('compose.restricted')
        : t('compose.failed');

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('compose.title') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[4] }}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('compose.kind')}
        </Text>
        <View style={styles.wrap} accessibilityRole="radiogroup">
          {KINDS.map((value) => (
            <Chip
              key={value}
              label={t(`post.kinds.${value}`)}
              selected={kind === value}
              onPress={() => setKind(value)}
              testID={`compose-kind-${value}`}
            />
          ))}
        </View>
        <TextField
          label={t('compose.body')}
          value={body}
          onChangeText={setBody}
          multiline
          maxLength={BODY_MAX}
          hint={t('compose.bodyHint', { count: BODY_MAX - body.length })}
          testID="compose-body"
        />
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('compose.place')}
        </Text>
        {destination ? (
          <View style={styles.row}>
            <Text
              style={[theme.typography.body, styles.fill, { color: theme.colors.textPrimary }]}
              testID="compose-destination"
            >
              {[destination.name, destination.country_name].filter(Boolean).join(', ')}
            </Text>
            <Button
              label={t('compose.changePlace')}
              variant="secondary"
              onPress={() => setDestination(null)}
            />
          </View>
        ) : (
          <View style={{ gap: theme.spacing[2] }}>
            <TextField
              label={t('compose.searchPlace')}
              value={search}
              onChangeText={setSearch}
              autoCorrect={false}
              hint={needsPlace ? t('compose.placeRequired') : t('compose.placeOptional')}
              testID="compose-search"
            />
            {(matches.data ?? []).map((match) => (
              <Pressable
                key={match.id}
                onPress={() => setDestination(match)}
                accessibilityRole="button"
                style={[styles.match, { borderColor: theme.colors.divider }]}
                testID={`compose-match-${match.slug}`}
              >
                <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                  {[match.name, match.country_name].filter(Boolean).join(', ')}
                </Text>
              </Pressable>
            ))}
          </View>
        )}
        <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
          {t('compose.audience')}
        </Text>
        <View style={styles.wrap} accessibilityRole="radiogroup">
          {VISIBILITIES.map((value) => (
            <Chip
              key={value}
              label={t(`compose.visibility.${value}`)}
              selected={visibility === value}
              onPress={() => setVisibility(value)}
              testID={`compose-visibility-${value}`}
            />
          ))}
        </View>
        {publish.isError ? (
          <Notice tone="error" testID="compose-error">
            {errorText}
          </Notice>
        ) : null}
        <Button
          label={t('compose.publish')}
          onPress={() => publish.mutate()}
          disabled={!canPublish}
          busy={publish.isPending}
          testID="compose-publish"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  chip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
    minHeight: 36,
  },
  match: { borderWidth: 1, borderRadius: 8, padding: 12 },
});
