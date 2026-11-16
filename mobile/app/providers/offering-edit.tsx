import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Chip } from '@/components/Chip';
import { Button, Notice, TextField } from '@/components/Form';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import type { DestinationSummary } from '@/features/feed/types';
import { ServerFeature } from '@/features/flags/serverFlags';
import {
  createOffering,
  getOffering,
  getWorkspace,
  OFFERING_KINDS,
  providerKeys,
  updateOffering,
  type Offering,
  type OfferingFields,
  type OfferingKind,
  type PriceUnit,
  type ProviderWorkspace,
} from '@/features/providers/api';
import { parseAmount } from '@/features/providers/format';
import { useAppTheme } from '@/theme/useAppTheme';

const CURRENCY_BY_COUNTRY: Record<string, string> = {
  BR: 'BRL',
  PT: 'EUR',
  ES: 'EUR',
  FR: 'EUR',
  DE: 'EUR',
  IT: 'EUR',
  NL: 'EUR',
  GB: 'GBP',
  US: 'USD',
  MX: 'MXN',
  AR: 'ARS',
  CL: 'CLP',
  CO: 'COP',
  PE: 'PEN',
  JP: 'JPY',
  TH: 'THB',
};

/** SCR-170 Create or edit an offering with an indicative "from" price (PROV-006). */
export default function OfferingEditScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <OfferingForm />
    </ServerFeature>
  );
}

function OfferingForm() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { providerId, offeringId } = useLocalSearchParams<{
    providerId: string;
    offeringId?: string;
  }>();
  const workspace = useQuery({
    queryKey: providerKeys.workspace(providerId),
    queryFn: () => getWorkspace(getApiClient(), providerId),
  });
  const existing = useQuery({
    queryKey: providerKeys.offering(offeringId ?? ''),
    queryFn: () => getOffering(getApiClient(), offeringId as string),
    enabled: Boolean(offeringId),
  });
  if (!workspace.data || (offeringId && !existing.data)) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <Stack.Screen options={{ headerShown: true, title: t('providers.offering') }} />
        {workspace.isError || existing.isError ? (
          <View style={{ padding: theme.spacing[4] }}>
            <Notice tone="error">{t('providers.offeringMissing')}</Notice>
          </View>
        ) : null}
      </SafeAreaView>
    );
  }
  return (
    <OfferingFormBody
      key={offeringId ?? 'new'}
      providerId={providerId}
      workspace={workspace.data}
      initial={existing.data ?? null}
    />
  );
}

function OfferingFormBody({
  providerId,
  workspace,
  initial,
}: {
  providerId: string;
  workspace: ProviderWorkspace;
  initial: Offering | null;
}) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const offeringId = initial?.id;
  const fallbackCurrency = CURRENCY_BY_COUNTRY[workspace.country_code] ?? 'USD';
  const [kind, setKind] = useState<OfferingKind>(initial?.kind ?? 'tour');
  const [title, setTitle] = useState(initial?.title ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [destination, setDestination] = useState<DestinationSummary | null>(
    initial ? initial.destination : workspace.base_destination,
  );
  const [hours, setHours] = useState(
    initial?.duration_minutes ? String(Math.round((initial.duration_minutes / 60) * 10) / 10) : '',
  );
  const [price, setPrice] = useState(
    initial?.price_from ? String(initial.price_from.amount_minor / 100) : '',
  );
  const [currency, setCurrency] = useState(initial?.price_from?.currency ?? fallbackCurrency);
  const [unit, setUnit] = useState<PriceUnit>(initial?.price_from?.unit ?? 'per_person');
  const [groupSize, setGroupSize] = useState(
    initial?.max_group_size ? String(initial.max_group_size) : '',
  );

  const amount = parseAmount(price);
  const durationHours = Number.parseFloat(hours.replace(',', '.'));
  const minutes = Number.isFinite(durationHours) ? Math.round(durationHours * 60) : null;
  const size = Number.parseInt(groupSize, 10);
  const valid =
    title.trim().length >= 3 &&
    destination !== null &&
    (price.trim() === '' || (amount !== null && /^[A-Z]{3}$/.test(currency))) &&
    (minutes === null || (minutes >= 15 && minutes <= 43200));

  const body = (): OfferingFields => ({
    kind,
    title: title.trim(),
    description: description.trim() || null,
    destination_id: (destination as DestinationSummary).id,
    duration_minutes: minutes,
    price_from_minor: price.trim() ? amount : null,
    currency: price.trim() ? currency : null,
    price_unit: price.trim() ? unit : null,
    max_group_size: Number.isInteger(size) && size > 0 ? size : null,
  });
  const save = useMutation({
    mutationFn: () =>
      offeringId && initial
        ? updateOffering(getApiClient(), offeringId, initial.version, body())
        : createOffering(getApiClient(), providerId, body()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['providers', 'offerings', providerId] });
      if (offeringId)
        void queryClient.invalidateQueries({ queryKey: providerKeys.offering(offeringId) });
      router.back();
    },
  });

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: offeringId
            ? t('providers.offeringsAdmin.editTitle')
            : t('providers.offeringsAdmin.new'),
        }}
      />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.chips}>
          {OFFERING_KINDS.map((value) => (
            <Chip
              key={value}
              label={t(`providers.offeringKind.${value}`)}
              selected={kind === value}
              onPress={() => setKind(value)}
              testID={`offering-kind-${value}`}
            />
          ))}
        </View>
        <TextField
          label={t('providers.offeringsAdmin.titleField')}
          value={title}
          onChangeText={setTitle}
          maxLength={100}
          testID="offering-title"
        />
        <DestinationPicker
          value={destination}
          onChange={setDestination}
          variant="destination"
          testID="offering-destination"
        />
        <TextField
          label={t('providers.offeringsAdmin.description')}
          value={description}
          onChangeText={setDescription}
          multiline
          maxLength={4000}
          testID="offering-description"
        />
        <TextField
          label={t('providers.offeringsAdmin.hours')}
          value={hours}
          onChangeText={setHours}
          keyboardType="decimal-pad"
          maxLength={5}
          testID="offering-hours"
        />
        <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
          {t('providers.offeringsAdmin.price')}
        </Text>
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('providers.offeringsAdmin.priceHint')}
        </Text>
        <View style={[styles.priceRow, { gap: theme.spacing[2] }]}>
          <View style={styles.fill}>
            <TextField
              label={t('providers.offeringsAdmin.amount')}
              value={price}
              onChangeText={setPrice}
              keyboardType="decimal-pad"
              maxLength={12}
              testID="offering-price"
            />
          </View>
          <View style={styles.currency}>
            <TextField
              label={t('providers.offeringsAdmin.currency')}
              value={currency}
              onChangeText={(value) => setCurrency(value.toUpperCase())}
              autoCapitalize="characters"
              maxLength={3}
              testID="offering-currency"
            />
          </View>
        </View>
        <View style={styles.chips}>
          {(['per_person', 'per_group'] as const).map((value) => (
            <Chip
              key={value}
              label={t(`providers.priceUnit.${value}`)}
              selected={unit === value}
              onPress={() => setUnit(value)}
              testID={`offering-unit-${value}`}
            />
          ))}
        </View>
        <TextField
          label={t('providers.offeringsAdmin.groupSize')}
          value={groupSize}
          onChangeText={setGroupSize}
          keyboardType="number-pad"
          maxLength={3}
          testID="offering-group-size"
        />
        {save.isError ? <Notice tone="error">{t('providers.offeringsAdmin.failed')}</Notice> : null}
        <Button
          label={t('providers.apply.save')}
          onPress={() => save.mutate()}
          disabled={!valid}
          busy={save.isPending}
          testID="offering-save"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  priceRow: { flexDirection: 'row', alignItems: 'flex-end' },
  currency: { width: 96 },
});
