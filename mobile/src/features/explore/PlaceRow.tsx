import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAppTheme } from '@/theme/useAppTheme';

import type { PlaceSummary } from './api';

export function PlaceRow({ place, onOpen }: { place: PlaceSummary; onOpen: () => void }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  return (
    <Pressable
      onPress={onOpen}
      accessibilityRole="link"
      accessibilityLabel={place.name}
      style={[styles.row, { borderColor: theme.colors.divider }]}
      testID={`place-${place.id}`}
    >
      <View style={styles.fill}>
        <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
          {place.name}
        </Text>
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t(`explore.categories.${place.category}`)}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 10 },
  fill: { flex: 1 },
});
