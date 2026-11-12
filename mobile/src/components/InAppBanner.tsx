import { router, type Href } from 'expo-router';
import { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { create } from 'zustand';

import { Avatar } from '@/features/feed/PostCard';
import type { UserSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

export interface Banner {
  id: string;
  title: string;
  body: string;
  user: UserSummary | null;
  href?: Href;
}

interface BannerState {
  banner: Banner | null;
  show: (banner: Banner) => void;
  hide: (id?: string) => void;
}

export const useBannerStore = create<BannerState>()((set, get) => ({
  banner: null,
  show: (banner) => set({ banner }),
  hide: (id) => {
    if (!id || get().banner?.id === id) set({ banner: null });
  },
}));

const VISIBLE_MS = 6000;

/** A short notice at the top of the screen for things that just happened (a friend request). */
export function InAppBannerHost() {
  const theme = useAppTheme();
  const insets = useSafeAreaInsets();
  const banner = useBannerStore((state) => state.banner);
  const hide = useBannerStore((state) => state.hide);

  useEffect(() => {
    if (!banner) return;
    const timer = setTimeout(() => hide(banner.id), VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [banner, hide]);

  if (!banner) return null;
  return (
    <View pointerEvents="box-none" style={[styles.host, { top: insets.top + 8 }]}>
      <Pressable
        onPress={() => {
          hide(banner.id);
          if (banner.href) router.push(banner.href);
        }}
        accessibilityRole="alert"
        accessibilityLabel={`${banner.title}. ${banner.body}`}
        style={[
          styles.card,
          { backgroundColor: theme.colors.surfaceRaised, borderColor: theme.colors.primary },
        ]}
        testID="in-app-banner"
      >
        <Avatar user={banner.user} size={36} />
        <View style={styles.text}>
          <Text
            style={[theme.typography.label, { color: theme.colors.textPrimary }]}
            numberOfLines={1}
          >
            {banner.title}
          </Text>
          <Text
            style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
            numberOfLines={2}
          >
            {banner.body}
          </Text>
        </View>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  host: { position: 'absolute', left: 12, right: 12, zIndex: 1000, elevation: 12 },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderRadius: 18,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  text: { flex: 1, gap: 2 },
});
