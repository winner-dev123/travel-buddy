import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text } from 'react-native';

import { getApiClient } from '@/api';
import { TextField } from '@/components/Form';
import { searchDestinations } from '@/features/feed/api';
import type { DestinationSummary } from '@/features/feed/types';
import { useAppTheme } from '@/theme/useAppTheme';

/** Search-as-you-type destination choice; tapping the chosen one starts over. */
export function DestinationPicker({
  value,
  onChange,
  testID,
  variant = 'places',
}: {
  value: DestinationSummary | null;
  onChange: (destination: DestinationSummary | null) => void;
  testID: string;
  /** "Places in Lisbon" in Explore; "Destination: Lisbon" where the city itself is chosen. */
  variant?: 'places' | 'destination';
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const [search, setSearch] = useState('');
  const matches = useQuery({
    queryKey: ['destinations', 'search', search],
    queryFn: () => searchDestinations(getApiClient(), search),
    enabled: !value && search.trim().length >= 2,
  });

  if (value) {
    return (
      <Pressable
        onPress={() => onChange(null)}
        accessibilityRole="button"
        testID={`${testID}-chosen`}
      >
        <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
          {variant === 'places'
            ? t('explore.where', { place: value.name })
            : t('explore.destinationChosen', { place: value.name })}
        </Text>
      </Pressable>
    );
  }
  return (
    <>
      <TextField
        label={t('explore.destination')}
        value={search}
        onChangeText={setSearch}
        autoCorrect={false}
        testID={testID}
      />
      {(matches.data ?? []).map((match) => (
        <Pressable
          key={match.id}
          onPress={() => {
            setSearch('');
            onChange(match);
          }}
          accessibilityRole="button"
          style={[styles.match, { borderColor: theme.colors.divider }]}
          testID={`${testID}-${match.slug}`}
        >
          <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
            {[match.name, match.country_name].filter(Boolean).join(', ')}
          </Text>
        </Pressable>
      ))}
    </>
  );
}

const styles = StyleSheet.create({
  match: { borderWidth: 1, borderRadius: 8, padding: 12 },
});
