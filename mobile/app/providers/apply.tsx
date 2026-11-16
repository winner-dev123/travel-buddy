import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Chip } from '@/components/Chip';
import { Button, Notice, TextField } from '@/components/Form';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import type { DestinationSummary } from '@/features/feed/types';
import { ServerFeature } from '@/features/flags/serverFlags';
import { pickPhotos, uploadPhoto } from '@/features/media/upload';
import {
  createProvider,
  getWorkspace,
  LANGUAGE_CHOICES,
  providerKeys,
  SPECIALTIES,
  updateProvider,
  type ProviderFields,
  type ProviderKind,
  type ProviderWorkspace,
  type Specialty,
} from '@/features/providers/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-167 Apply as a guide or company, or edit the profile later (PROV-001, PROV-002). */
export default function ApplyScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <ProviderForm />
    </ServerFeature>
  );
}

function ProviderForm() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const existing = useQuery({
    queryKey: providerKeys.workspace(id ?? ''),
    queryFn: () => getWorkspace(getApiClient(), id as string),
    enabled: Boolean(id),
  });
  if (id && !existing.data) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <Stack.Screen options={{ headerShown: true, title: t('providers.apply.editTitle') }} />
        {existing.isError ? (
          <View style={{ padding: theme.spacing[4] }}>
            <Notice tone="error">{t('providers.missing')}</Notice>
          </View>
        ) : null}
      </SafeAreaView>
    );
  }
  return <ProviderFormBody key={id ?? 'new'} id={id} initial={existing.data ?? null} />;
}

function ProviderFormBody({ id, initial }: { id?: string; initial: ProviderWorkspace | null }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const editing = Boolean(id);
  const [key] = useState(() => getApiClient().newIdempotencyKey());
  const [kind, setKind] = useState<ProviderKind>(initial?.kind ?? 'guide');
  const [name, setName] = useState(initial?.display_name ?? '');
  const [legalName, setLegalName] = useState(initial?.legal_name ?? '');
  const [registration, setRegistration] = useState(initial?.registration_number ?? '');
  const [base, setBase] = useState<DestinationSummary | null>(initial?.base_destination ?? null);
  const [tagline, setTagline] = useState(initial?.tagline ?? '');
  const [about, setAbout] = useState(initial?.about ?? '');
  const [years, setYears] = useState(
    initial?.years_experience !== null && initial?.years_experience !== undefined
      ? String(initial.years_experience)
      : '',
  );
  const [website, setWebsite] = useState(initial?.website_url ?? '');
  const [languages, setLanguages] = useState<string[]>(initial?.languages ?? []);
  const [specialties, setSpecialties] = useState<Specialty[]>(initial?.specialties ?? []);
  const [logo, setLogo] = useState<{ id: string; uri: string | null } | null>(
    initial?.logo ? { id: initial.logo.id, uri: initial.logo.url } : null,
  );
  const [uploading, setUploading] = useState(false);
  const locked = new Set(initial?.locked_fields ?? []);

  const toggle = <T,>(list: T[], value: T, max: number): T[] =>
    list.includes(value)
      ? list.filter((v) => v !== value)
      : list.length < max
        ? [...list, value]
        : list;

  const chooseLogo = async () => {
    const [photo] = await pickPhotos(1);
    if (!photo) return;
    setUploading(true);
    try {
      const mediaId = await uploadPhoto(getApiClient(), photo, 'provider');
      setLogo({ id: mediaId, uri: photo.uri });
    } finally {
      setUploading(false);
    }
  };

  const fields = (): ProviderFields => {
    const parsedYears = Number.parseInt(years, 10);
    const body: ProviderFields = {
      display_name: name.trim(),
      tagline: tagline.trim() || null,
      about: about.trim() || null,
      languages,
      specialties,
      years_experience: Number.isInteger(parsedYears) ? parsedYears : null,
      website_url: website.trim() || null,
      logo_media_id: logo?.id ?? null,
    };
    if (base && base.id !== initial?.base_destination?.id) {
      body.base_destination_id = base.id;
    }
    if (!locked.has('legal_name')) body.legal_name = legalName.trim() || null;
    if (!locked.has('registration_number')) body.registration_number = registration.trim() || null;
    if (!locked.has('country_code') && base) body.country_code = base.country_code;
    return body;
  };
  const save = useMutation({
    mutationFn: () =>
      editing && initial
        ? updateProvider(getApiClient(), id as string, initial.version, fields())
        : createProvider(getApiClient(), key, {
            ...fields(),
            kind,
            country_code: (base as DestinationSummary).country_code,
            base_destination_id: (base as DestinationSummary).id,
          }),
    onSuccess: (workspace) => {
      queryClient.setQueryData(providerKeys.workspace(workspace.id), workspace);
      void queryClient.invalidateQueries({ queryKey: providerKeys.mine });
      if (editing) router.back();
      else router.replace({ pathname: '/providers/workspace/[id]', params: { id: workspace.id } });
    },
  });
  const problem =
    save.error instanceof ApiProblem
      ? save.error.code === 'guide_profile_exists'
        ? t('providers.apply.guideExists')
        : save.error.code === 'email_unverified'
          ? t('providers.request.verifyEmail')
          : save.error.code === 'provider_field_locked'
            ? t('providers.apply.locked')
            : t('providers.apply.failed')
      : save.error
        ? t('providers.apply.failed')
        : null;
  const valid = name.trim().length >= 2 && base !== null && !uploading;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen
        options={{
          headerShown: true,
          title: editing ? t('providers.apply.editTitle') : t('providers.apply.title'),
        }}
      />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        {!editing ? (
          <>
            <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
              {t('providers.apply.intro')}
            </Text>
            <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
              {t('providers.apply.kind')}
            </Text>
            <View style={styles.chips}>
              {(['guide', 'company'] as const).map((value) => (
                <Chip
                  key={value}
                  label={t(`providers.apply.kindOption.${value}`)}
                  selected={kind === value}
                  onPress={() => setKind(value)}
                  testID={`apply-kind-${value}`}
                />
              ))}
            </View>
          </>
        ) : null}
        <TextField
          label={t('providers.apply.name')}
          hint={t('providers.apply.nameHint')}
          value={name}
          onChangeText={setName}
          maxLength={80}
          testID="apply-name"
        />
        <DestinationPicker
          value={base}
          onChange={setBase}
          variant="destination"
          label={t('providers.apply.base')}
          testID="apply-base"
        />
        <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
          {t('providers.apply.verification')}
        </Text>
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('providers.apply.verificationNote')}
        </Text>
        <TextField
          label={
            kind === 'company'
              ? t('providers.apply.legalCompany')
              : t('providers.apply.legalPerson')
          }
          value={legalName}
          onChangeText={setLegalName}
          editable={!locked.has('legal_name')}
          maxLength={200}
          testID="apply-legal-name"
        />
        <TextField
          label={t('providers.apply.registration')}
          hint={t('providers.apply.registrationHint')}
          value={registration}
          onChangeText={setRegistration}
          editable={!locked.has('registration_number')}
          autoCapitalize="characters"
          maxLength={64}
          testID="apply-registration"
        />
        {locked.size > 0 ? <Notice tone="info">{t('providers.apply.locked')}</Notice> : null}

        <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
          {t('providers.apply.publicProfile')}
        </Text>
        <View style={[styles.logoRow, { gap: theme.spacing[3] }]}>
          {logo?.uri ? (
            <Image
              source={{ uri: logo.uri }}
              style={styles.logo}
              accessibilityIgnoresInvertColors
            />
          ) : null}
          <Button
            label={logo ? t('providers.apply.changeLogo') : t('providers.apply.addLogo')}
            variant="secondary"
            icon="image-outline"
            onPress={() => void chooseLogo()}
            busy={uploading}
            testID="apply-logo"
          />
        </View>
        <TextField
          label={t('providers.apply.tagline')}
          value={tagline}
          onChangeText={setTagline}
          maxLength={120}
          testID="apply-tagline"
        />
        <TextField
          label={t('providers.apply.about')}
          value={about}
          onChangeText={setAbout}
          multiline
          maxLength={4000}
          testID="apply-about"
        />
        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('providers.apply.languages')}
        </Text>
        <View style={styles.chips}>
          {LANGUAGE_CHOICES.map((code) => (
            <Chip
              key={code}
              label={t(`providers.language.${code}`)}
              selected={languages.some((l) => l === code || l.startsWith(`${code}-`))}
              onPress={() =>
                setLanguages((list) =>
                  list.some((l) => l === code || l.startsWith(`${code}-`))
                    ? list.filter((l) => l !== code && !l.startsWith(`${code}-`))
                    : toggle(list, code, 12),
                )
              }
              testID={`apply-language-${code}`}
            />
          ))}
        </View>
        <Text style={[theme.typography.label, { color: theme.colors.textSecondary }]}>
          {t('providers.apply.specialties')}
        </Text>
        <View style={styles.chips}>
          {SPECIALTIES.map((value) => (
            <Chip
              key={value}
              label={t(`providers.specialty.${value}`)}
              selected={specialties.includes(value)}
              onPress={() => setSpecialties((list) => toggle(list, value, 8))}
              testID={`apply-specialty-${value}`}
            />
          ))}
        </View>
        <TextField
          label={t('providers.apply.years')}
          value={years}
          onChangeText={setYears}
          keyboardType="number-pad"
          maxLength={2}
          testID="apply-years"
        />
        <TextField
          label={t('providers.apply.website')}
          value={website}
          onChangeText={setWebsite}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          maxLength={300}
          testID="apply-website"
        />
        {problem ? (
          <Notice tone="error" testID="apply-error">
            {problem}
          </Notice>
        ) : null}
        <Button
          label={editing ? t('providers.apply.save') : t('providers.apply.create')}
          onPress={() => save.mutate()}
          disabled={!valid}
          busy={save.isPending}
          testID="apply-save"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  logoRow: { flexDirection: 'row', alignItems: 'center' },
  logo: { width: 56, height: 56, borderRadius: 28 },
});
