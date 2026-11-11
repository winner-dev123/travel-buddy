import Ionicons from '@expo/vector-icons/Ionicons';
import { LinearGradient } from 'expo-linear-gradient';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FlatList,
  Image,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { MediaRef } from '@/features/feed/types';
import { fontFamilies, scrims } from '@/theme/tokens';
import { useAppTheme } from '@/theme/useAppTheme';

export function MediaPreview({ media, bleed = false }: { media: MediaRef; bleed?: boolean }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const ratio = media.width && media.height ? media.width / media.height : 4 / 3;
  const corner = { borderRadius: bleed ? 0 : theme.radii.md };
  if (media.status === 'ready' && media.url) {
    return (
      <Image
        source={{ uri: media.url }}
        style={[
          styles.media,
          corner,
          // Cover photos stay between 4:5 and 16:10 so a feed of them keeps an even rhythm.
          { aspectRatio: Math.max(bleed ? 0.8 : 0.6, Math.min(ratio, bleed ? 1.6 : 2)) },
        ]}
        accessibilityLabel={media.alt_text ?? t('post.photo')}
      />
    );
  }
  return (
    <View
      style={[
        styles.media,
        styles.center,
        corner,
        { aspectRatio: 4 / 3, backgroundColor: theme.colors.surface },
      ]}
    >
      <Ionicons
        name={media.status === 'processing' ? 'hourglass-outline' : 'image-outline'}
        size={22}
        color={theme.colors.textSecondary}
        accessible={false}
      />
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {media.status === 'processing' ? t('post.photoProcessing') : t('post.photoUnavailable')}
      </Text>
    </View>
  );
}

/**
 * A story's photos. In lists (`compact`) the first one is an edge-to-edge cover with a "+N" badge
 * and, when given, the `place` it was taken at; on the story itself all of them are shown, and
 * tapping a ready photo opens it full screen (SCR-137) to swipe through.
 */
export function PhotoGallery({
  media,
  compact,
  place,
}: {
  media: MediaRef[];
  compact: boolean;
  place?: string;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const photos = media.filter((item) => item.kind === 'image');
  const [open, setOpen] = useState<number | null>(null);
  if (photos.length === 0) return null;
  const viewable = photos.filter((photo) => photo.status === 'ready' && photo.url);
  const openAt = (photo: MediaRef) => {
    const index = viewable.indexOf(photo);
    if (index >= 0) setOpen(index);
  };
  const shown = compact ? photos.slice(0, 1) : photos;
  const coverReady = photos[0]?.status === 'ready' && Boolean(photos[0].url);

  return (
    <View style={{ gap: theme.spacing[2] }} testID="post-photos">
      {shown.map((photo, index) => (
        <Pressable
          key={photo.id}
          onPress={compact ? undefined : () => openAt(photo)}
          disabled={compact}
          accessibilityRole={compact ? undefined : 'imagebutton'}
          accessibilityLabel={compact ? undefined : t('post.openPhoto', { number: index + 1 })}
          testID={`post-photo-${index}`}
        >
          <MediaPreview media={photo} bleed={compact} />
          {compact && coverReady && place ? (
            <LinearGradient
              colors={scrims.photo}
              style={styles.scrim}
              pointerEvents="none"
              testID="post-photo-scrim"
            />
          ) : null}
          {compact && place ? (
            <View style={[styles.badge, styles.place]} testID="post-photo-place">
              <Ionicons name="location-sharp" size={13} color={scrims.onPhoto} accessible={false} />
              <Text style={[theme.typography.caption, styles.onPhoto]} numberOfLines={1}>
                {place}
              </Text>
            </View>
          ) : null}
          {compact && photos.length > 1 ? (
            <View style={[styles.badge, styles.more]} testID="post-more-photos">
              <Ionicons name="images-outline" size={13} color={scrims.onPhoto} accessible={false} />
              <Text style={[theme.typography.caption, styles.onPhoto]}>
                {`+${photos.length - 1}`}
              </Text>
            </View>
          ) : null}
        </Pressable>
      ))}
      {open !== null ? (
        <PhotoViewer photos={viewable} start={open} onClose={() => setOpen(null)} />
      ) : null}
    </View>
  );
}

function PhotoViewer({
  photos,
  start,
  onClose,
}: {
  photos: MediaRef[];
  start: number;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { width } = useWindowDimensions();
  const [index, setIndex] = useState(start);
  return (
    <Modal visible animationType="fade" onRequestClose={onClose} testID="photo-viewer">
      <SafeAreaView style={styles.viewer}>
        <View style={styles.viewerBar}>
          <Text style={styles.viewerText} testID="photo-viewer-count">
            {t('post.photoCount', { number: index + 1, total: photos.length })}
          </Text>
          <Pressable
            onPress={onClose}
            accessibilityRole="button"
            accessibilityLabel={t('post.closePhoto')}
            hitSlop={12}
            style={styles.viewerClose}
            testID="photo-viewer-close"
          >
            <Ionicons name="close" size={22} color={scrims.onPhoto} accessible={false} />
          </Pressable>
        </View>
        <FlatList
          data={photos}
          horizontal
          pagingEnabled
          initialScrollIndex={start}
          getItemLayout={(_, i) => ({ length: width, offset: width * i, index: i })}
          keyExtractor={(photo) => photo.id}
          showsHorizontalScrollIndicator={false}
          onMomentumScrollEnd={(event) =>
            setIndex(Math.round(event.nativeEvent.contentOffset.x / width))
          }
          renderItem={({ item }) => (
            <View style={[styles.page, { width }]}>
              <Image
                source={{ uri: item.url as string }}
                style={styles.full}
                resizeMode="contain"
                accessibilityLabel={item.alt_text ?? t('post.photo')}
              />
            </View>
          )}
        />
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  media: { width: '100%' },
  center: { alignItems: 'center', justifyContent: 'center', gap: 6 },
  scrim: { position: 'absolute', left: 0, right: 0, bottom: 0, height: '45%' },
  // Photo overlays use fixed colours in both themes: they sit on a picture, not on a surface.
  badge: {
    position: 'absolute',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: scrims.photoChip,
  },
  place: { left: 12, bottom: 12, maxWidth: '75%' },
  more: { right: 12, top: 12 },
  onPhoto: { color: scrims.onPhoto, flexShrink: 1 },
  viewer: { flex: 1, backgroundColor: '#000000' },
  viewerBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  viewerText: { color: scrims.onPhoto, fontSize: 15, fontFamily: fontFamilies.semibold },
  viewerClose: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: scrims.photoChip,
  },
  page: { justifyContent: 'center' },
  full: { width: '100%', height: '100%' },
});
