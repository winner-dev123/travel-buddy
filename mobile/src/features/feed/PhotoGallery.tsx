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
import { useAppTheme } from '@/theme/useAppTheme';

export function MediaPreview({ media }: { media: MediaRef }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const ratio = media.width && media.height ? media.width / media.height : 4 / 3;
  if (media.status === 'ready' && media.url) {
    return (
      <Image
        source={{ uri: media.url }}
        style={[styles.media, { aspectRatio: Math.max(0.6, Math.min(ratio, 2)) }]}
        accessibilityLabel={media.alt_text ?? t('post.photo')}
      />
    );
  }
  return (
    <View
      style={[
        styles.media,
        styles.center,
        { aspectRatio: 4 / 3, backgroundColor: theme.colors.surface },
      ]}
    >
      <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
        {media.status === 'processing' ? t('post.photoProcessing') : t('post.photoUnavailable')}
      </Text>
    </View>
  );
}

/** A story's photos: the first with a "+N" badge in lists (`compact`), all of them on the story
 * itself. Tapping a ready photo opens it full screen (SCR-137) to swipe through. */
export function PhotoGallery({ media, compact }: { media: MediaRef[]; compact: boolean }) {
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
          <MediaPreview media={photo} />
          {compact && photos.length > 1 ? (
            <View
              style={[styles.more, { backgroundColor: theme.colors.background }]}
              testID="post-more-photos"
            >
              <Text style={[theme.typography.label, { color: theme.colors.textPrimary }]}>
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
            testID="photo-viewer-close"
          >
            <Text style={styles.viewerText}>✕</Text>
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
  media: { width: '100%', borderRadius: 8 },
  center: { alignItems: 'center', justifyContent: 'center' },
  more: {
    position: 'absolute',
    right: 8,
    bottom: 8,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  viewer: { flex: 1, backgroundColor: '#000' },
  viewerBar: { flexDirection: 'row', justifyContent: 'space-between', padding: 16 },
  viewerText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  page: { justifyContent: 'center' },
  full: { width: '100%', height: '100%' },
});
