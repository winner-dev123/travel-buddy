import Ionicons from '@expo/vector-icons/Ionicons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { searchPlaces, type PlaceSummary } from '@/features/explore/api';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import { createPost, feedKeys, type NewPost } from '@/features/feed/api';
import type { DestinationSummary, PostKind } from '@/features/feed/types';
import {
  MAX_PHOTOS,
  PhotoUploadError,
  pickPhotos,
  takePhoto,
  UnsupportedPhotoError,
  uploadPhoto,
  type DraftPhoto,
} from '@/features/media/upload';
import { useAppTheme } from '@/theme/useAppTheme';

const KINDS: PostKind[] = [
  'tip',
  'photo',
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

/** SCR-030 Composer: stories with up to ten photos and an optional destination. */
export default function ComposeScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<PostKind>('tip');
  const [body, setBody] = useState('');
  const [visibility, setVisibility] = useState<NewPost['visibility']>('public');
  const [destination, setDestination] = useState<DestinationSummary | null>(null);
  const [spotSearch, setSpotSearch] = useState('');
  const [spot, setSpot] = useState<PlaceSummary | null>(null);
  const [photos, setPhotos] = useState<DraftPhoto[]>([]);
  const [photoNotice, setPhotoNotice] = useState<string | null>(null);
  // One key for this draft: a retried submit never creates a second post.
  const [firstKey] = useState(() => getApiClient().newIdempotencyKey());
  const idempotencyKey = useRef(firstKey);

  const changePhotos = (next: DraftPhoto[]) => {
    setPhotos(next);
    // A different set of photos is a different request: retrying must not reuse the old key.
    idempotencyKey.current = getApiClient().newIdempotencyKey();
  };
  const addPhotos = async (source: 'library' | 'camera') => {
    setPhotoNotice(null);
    try {
      const picked =
        source === 'library' ? await pickPhotos(MAX_PHOTOS - photos.length) : await takePhoto();
      if (picked === 'denied') setPhotoNotice(t('compose.cameraDenied'));
      else if (picked.length) changePhotos([...photos, ...picked].slice(0, MAX_PHOTOS));
    } catch (error) {
      setPhotoNotice(
        error instanceof UnsupportedPhotoError
          ? t('compose.photoUnsupported')
          : t('compose.photoFailed'),
      );
    }
  };

  // POST-002: optionally tag a public place in the chosen destination.
  const spots = useQuery({
    queryKey: ['places', 'search', destination?.id ?? '', spotSearch],
    queryFn: () => searchPlaces(getApiClient(), destination?.id ?? '', spotSearch.trim()),
    enabled: destination !== null && spot === null && spotSearch.trim().length >= 2,
  });
  const chooseDestination = (next: DestinationSummary | null) => {
    setDestination(next);
    setSpot(null);
    setSpotSearch('');
  };

  const publish = useMutation({
    mutationFn: async () => {
      const client = getApiClient();
      const uploaded = [...photos];
      for (const [index, photo] of uploaded.entries()) {
        if (photo.mediaId) continue;
        uploaded[index] = { ...photo, mediaId: await uploadPhoto(client, photo) };
        setPhotos([...uploaded]); // keep progress: a retry skips photos already on the server
      }
      return createPost(
        client,
        {
          kind,
          body: body.trim(),
          visibility,
          destination,
          place: spot,
          mediaIds: uploaded.map((photo) => photo.mediaId as string),
        },
        idempotencyKey.current,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: feedKeys.all });
      router.back();
    },
  });

  const needsPlace = LOCATED.has(kind) && destination === null;
  const needsPhoto = kind === 'photo' && photos.length === 0;
  const canPublish = (body.trim().length > 0 || photos.length > 0) && !needsPlace && !needsPhoto;
  const errorText =
    publish.error instanceof PhotoUploadError ||
    (publish.error instanceof ApiProblem && publish.error.code === 'conflict')
      ? t('compose.uploadFailed')
      : publish.error instanceof ApiProblem && publish.error.code === 'email_unverified'
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
          {t('compose.photos')}
        </Text>
        {photos.length ? (
          <View style={styles.wrap} testID="compose-photos">
            {photos.map((photo, index) => (
              <View key={photo.uri}>
                <Image
                  source={{ uri: photo.uri }}
                  style={[styles.thumb, { backgroundColor: theme.colors.surface }]}
                  accessibilityIgnoresInvertColors
                />
                <Pressable
                  onPress={() => changePhotos(photos.filter((other) => other !== photo))}
                  disabled={publish.isPending}
                  accessibilityRole="button"
                  accessibilityLabel={t('compose.removePhoto', { index: index + 1 })}
                  hitSlop={8}
                  style={[styles.remove, { backgroundColor: theme.colors.background }]}
                  testID={`compose-photo-remove-${index}`}
                >
                  <Ionicons name="close" size={16} color={theme.colors.textPrimary} />
                </Pressable>
              </View>
            ))}
          </View>
        ) : null}
        {photos.length < MAX_PHOTOS ? (
          <View style={styles.row}>
            <Button
              label={t('compose.addPhotos')}
              variant="secondary"
              onPress={() => void addPhotos('library')}
              disabled={publish.isPending}
              testID="compose-add-photos"
            />
            <Button
              label={t('compose.takePhoto')}
              variant="secondary"
              onPress={() => void addPhotos('camera')}
              disabled={publish.isPending}
              testID="compose-take-photo"
            />
          </View>
        ) : null}
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {needsPhoto
            ? t('compose.photoRequired')
            : t('compose.photosLeft', { count: MAX_PHOTOS - photos.length })}
        </Text>
        {photoNotice ? (
          <Notice tone="info" testID="compose-photo-notice">
            {photoNotice}
          </Notice>
        ) : null}
        <DestinationPicker
          value={destination}
          onChange={chooseDestination}
          onPlace={(place, where) => {
            // A tourist place picked in search: its town is the destination, the place is tagged.
            setDestination(where);
            setSpot(place);
            setSpotSearch('');
          }}
          label={t('compose.place')}
          variant="destination"
          testID="compose-destination"
        />
        {destination === null ? (
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {needsPlace ? t('compose.placeRequired') : t('compose.placeOptional')}
          </Text>
        ) : null}
        {destination && spot ? (
          <View style={styles.row}>
            <Text
              style={[theme.typography.body, styles.fill, { color: theme.colors.textPrimary }]}
              testID="compose-spot"
            >
              {`📍 ${spot.name}`}
            </Text>
            <Button
              label={t('compose.removeSpot')}
              variant="secondary"
              onPress={() => setSpot(null)}
            />
          </View>
        ) : destination ? (
          <View style={{ gap: theme.spacing[2] }}>
            <TextField
              label={t('compose.spot')}
              value={spotSearch}
              onChangeText={setSpotSearch}
              autoCorrect={false}
              hint={t('compose.spotHint', { place: destination.name })}
              testID="compose-spot-search"
            />
            {(spots.data ?? []).map((match) => (
              <Pressable
                key={match.id}
                onPress={() => setSpot(match)}
                accessibilityRole="button"
                style={[styles.match, { borderColor: theme.colors.divider }]}
                testID={`compose-spot-${match.id}`}
              >
                <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                  {match.name}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
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
  thumb: { width: 88, height: 88, borderRadius: 8 },
  remove: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
