import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PlaceSummary } from '@/features/explore/api';
import type { DestinationSummary } from '@/features/feed/types';
import type { Suggestion } from '@/features/search/api';
import { PlaceSearchSheet } from '@/features/search/PlaceSearchSheet';
import { useAppTheme } from '@/theme/useAppTheme';

/**
 * A "Where to?" field that opens the full-screen search (ADR-0035). Choosing a town, a
 * neighbourhood or a country sets the destination; choosing a tourist place calls `onPlace`
 * when the screen can use it (Explore opens the place) and otherwise sets the town it is in.
 * Tapping the chosen destination opens the search again to change it.
 */
export function DestinationPicker({
  value,
  onChange,
  onPlace,
  testID,
  variant = 'places',
  label,
}: {
  value: DestinationSummary | null;
  onChange: (destination: DestinationSummary | null) => void;
  onPlace?: (place: PlaceSummary, destination: DestinationSummary) => void;
  testID: string;
  /** "Places in Lisbon" in Explore; "Destination: Lisbon" where the city itself is chosen. */
  variant?: 'places' | 'destination';
  /** The field's label; the generic "Destination" by default. */
  label?: string;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const [open, setOpen] = useState(false);
  const fieldLabel = label ?? t('explore.destination');

  const select = (suggestion: Suggestion) => {
    if (suggestion.type === 'place' && onPlace) {
      onPlace(suggestion.place, suggestion.destination);
      return;
    }
    onChange(suggestion.destination);
  };

  const chosen = value
    ? variant === 'places'
      ? t('explore.where', { place: value.name })
      : t('explore.destinationChosen', { place: value.name })
    : null;
  const where = value ? [value.region_name, value.country_name].filter(Boolean).join(', ') : '';

  return (
    <View style={{ gap: theme.spacing[2] }}>
      <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
        {fieldLabel}
      </Text>
      <Pressable
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        accessibilityLabel={chosen ? `${chosen}. ${t('search.change')}` : fieldLabel}
        accessibilityHint={t('search.openHint')}
        style={({ pressed }) => [
          styles.field,
          {
            backgroundColor: theme.colors.surface,
            borderColor: theme.colors.borderStrong,
            borderRadius: theme.radii.md,
            opacity: pressed ? 0.7 : 1,
          },
        ]}
        testID={value ? `${testID}-chosen` : testID}
      >
        <Ionicons
          name={value ? 'location' : 'search'}
          size={18}
          color={value ? theme.colors.primary : theme.colors.textSecondary}
        />
        <View style={styles.texts}>
          <Text
            numberOfLines={1}
            style={[
              value ? theme.typography.bodyStrong : theme.typography.body,
              { color: value ? theme.colors.textPrimary : theme.colors.textSecondary },
            ]}
          >
            {chosen ?? t('search.where')}
          </Text>
          {where ? (
            <Text
              numberOfLines={1}
              style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
            >
              {where}
            </Text>
          ) : null}
        </View>
        {value ? (
          <Pressable
            onPress={() => onChange(null)}
            accessibilityRole="button"
            accessibilityLabel={t('search.clear')}
            hitSlop={10}
            testID={`${testID}-clear`}
          >
            <Ionicons name="close-circle" size={20} color={theme.colors.textSecondary} />
          </Pressable>
        ) : null}
      </Pressable>
      <PlaceSearchSheet
        visible={open}
        onClose={() => setOpen(false)}
        onSelect={select}
        testID={testID}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderWidth: 1,
    paddingHorizontal: 14,
    minHeight: 52,
  },
  texts: { flex: 1, gap: 2 },
});
