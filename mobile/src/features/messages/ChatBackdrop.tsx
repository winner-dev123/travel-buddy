import { Image, StyleSheet, View, type ImageSourcePropType } from 'react-native';

import { BUILTIN_BACKGROUNDS, type ChatBackground } from '@/state/chatPreferences';
import { useAppTheme } from '@/theme/useAppTheme';

/** Where a chat background's picture comes from (null: the plain theme background). */
export function backgroundSource(background: ChatBackground): ImageSourcePropType | null {
  if (background.kind === 'builtin') return BUILTIN_BACKGROUNDS[background.id];
  if (background.kind === 'photo') return { uri: background.uri };
  return null;
}

/**
 * The chat background chosen in SCR-119, under a scrim in the theme's background colour so
 * bubbles and captions keep their contrast on any photo.
 */
export function ChatBackdrop({
  background,
  testID = 'chat-background',
}: {
  background: ChatBackground;
  testID?: string;
}) {
  const theme = useAppTheme();
  const source = backgroundSource(background);
  if (!source) return null;
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none" testID={testID}>
      <Image
        source={source}
        style={StyleSheet.absoluteFill}
        resizeMode="cover"
        accessibilityIgnoresInvertColors
      />
      <View
        style={[
          StyleSheet.absoluteFill,
          {
            backgroundColor: theme.colors.background,
            opacity: theme.scheme === 'dark' ? 0.62 : 0.55,
          },
        ]}
      />
    </View>
  );
}
