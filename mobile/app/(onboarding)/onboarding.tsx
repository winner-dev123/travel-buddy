import { useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { describeAuthError } from '@/auth/errors';
import { takeHomeRoute, useSessionStore } from '@/auth/sessionStore';
import { FeatureGate } from '@/components/FeatureGate';
import { Button, Notice, TextField } from '@/components/Form';
import { refreshMe, updateProfile } from '@/features/account/api';
import { DestinationPicker } from '@/features/explore/DestinationPicker';
import type { DestinationSummary } from '@/features/feed/types';
import { SUPPORTED_LOCALES, type SupportedLocale } from '@/i18n/locales';
import { useSettingsStore } from '@/state/settingsStore';
import { useAppTheme } from '@/theme/useAppTheme';

/** Native names: a language list is read by people who may not read the current UI language. */
const LANGUAGE_NAMES: Record<SupportedLocale, string> = {
  en: 'English',
  es: 'Español',
  'pt-BR': 'Português (Brasil)',
  fr: 'Français',
  de: 'Deutsch',
};
const INTERESTS = [
  'food',
  'culture',
  'history',
  'nature',
  'hiking',
  'beaches',
  'nightlife',
  'art',
  'photography',
  'budget',
] as const;
const STEPS = ['profile', 'language', 'interests', 'destination'] as const;
type Step = (typeof STEPS)[number];

function Choice({
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
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      style={[
        styles.choice,
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

/** SCR-010 Onboarding (PROF-001/002): profile, language, interests, destination, then the feed. */
export default function OnboardingScreen() {
  return (
    <FeatureGate feature="onboarding">
      <OnboardingWizard />
    </FeatureGate>
  );
}

function OnboardingWizard() {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const me = useSessionStore((state) => state.me);
  const setLocaleOverride = useSettingsStore((state) => state.setLocaleOverride);
  const [index, setIndex] = useState(0);
  const [displayName, setDisplayName] = useState(me?.profile.display_name ?? '');
  const [interests, setInterests] = useState<string[]>([]);
  const [destination, setDestination] = useState<DestinationSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const step: Step = STEPS[index] ?? 'profile';

  if (!me) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <View style={{ padding: theme.spacing[6], gap: theme.spacing[4] }}>
          <Notice tone="info">{t('onboarding.signInFirst')}</Notice>
          <Button label={t('account.goToSignIn')} onPress={() => router.replace('/sign-in')} />
        </View>
      </SafeAreaView>
    );
  }

  async function save(action: () => Promise<unknown>, next: () => void): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      await action();
      next();
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  const advance = () => setIndex((i) => Math.min(i + 1, STEPS.length - 1));
  const finish = (chosen: DestinationSummary | null) =>
    save(
      async () => {
        const client = getApiClient();
        if (chosen) {
          await client.put('/v1/users/me/browse-destination', {
            body: { destination_id: chosen.id },
          });
        }
        await client.post('/v1/users/me/onboarding/complete');
        await refreshMe(client);
      },
      () => router.replace(takeHomeRoute()),
    );

  const onNext = () => {
    if (step === 'profile') {
      void save(() => updateProfile(getApiClient(), { display_name: displayName.trim() }), advance);
    } else if (step === 'language') {
      void save(
        () =>
          getApiClient().patch('/v1/users/me/preferences', {
            body: { ui_locale: i18n.language },
          }),
        advance,
      );
    } else if (step === 'interests') {
      void save(
        () =>
          interests.length
            ? getApiClient().patch('/v1/users/me', { body: { interests } })
            : Promise.resolve(),
        advance,
      );
    } else {
      void finish(destination);
    }
  };

  const title = (text: string, hint: string) => (
    <View style={{ gap: theme.spacing[2] }}>
      <Text
        accessibilityRole="header"
        style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
      >
        {text}
      </Text>
      <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>{hint}</Text>
    </View>
  );

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[5] }}
        keyboardShouldPersistTaps="handled"
        testID={`onboarding-${step}`}
      >
        <Text
          style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
          testID="onboarding-progress"
        >
          {t('onboarding.progress', { current: index + 1, total: STEPS.length })}
        </Text>
        {step === 'profile' ? (
          <>
            {title(t('onboarding.profileTitle'), t('onboarding.profileHint'))}
            <TextField
              label={t('account.displayName')}
              value={displayName}
              onChangeText={setDisplayName}
              maxLength={50}
              testID="onboarding-display-name"
            />
          </>
        ) : null}
        {step === 'language' ? (
          <>
            {title(t('onboarding.languageTitle'), t('onboarding.languageHint'))}
            <View style={styles.wrap} accessibilityRole="radiogroup">
              {SUPPORTED_LOCALES.map((locale) => (
                <Choice
                  key={locale}
                  label={LANGUAGE_NAMES[locale]}
                  selected={i18n.language === locale}
                  onPress={() => {
                    setLocaleOverride(locale);
                    void i18n.changeLanguage(locale);
                  }}
                  testID={`onboarding-language-${locale}`}
                />
              ))}
            </View>
          </>
        ) : null}
        {step === 'interests' ? (
          <>
            {title(t('onboarding.interestsTitle'), t('onboarding.interestsHint'))}
            <View style={styles.wrap}>
              {INTERESTS.map((interest) => {
                const selected = interests.includes(interest);
                return (
                  <Choice
                    key={interest}
                    label={t(`onboarding.interests.${interest}`)}
                    selected={selected}
                    onPress={() =>
                      setInterests((current) =>
                        selected ? current.filter((i) => i !== interest) : [...current, interest],
                      )
                    }
                    testID={`onboarding-interest-${interest}`}
                  />
                );
              })}
            </View>
          </>
        ) : null}
        {step === 'destination' ? (
          <>
            {title(t('onboarding.destinationTitle'), t('onboarding.destinationHint'))}
            <DestinationPicker
              value={destination}
              onChange={setDestination}
              label={t('compose.searchPlace')}
              variant="destination"
              testID="onboarding-place"
            />
          </>
        ) : null}
        {error ? <Notice tone="error">{error}</Notice> : null}
        <Button
          label={step === 'destination' ? t('onboarding.finish') : t('onboarding.next')}
          onPress={onNext}
          busy={busy}
          disabled={step === 'profile' && !displayName.trim()}
          testID="onboarding-next"
        />
        {step === 'interests' || step === 'destination' ? (
          <Button
            label={t('onboarding.skip')}
            variant="secondary"
            onPress={step === 'destination' ? () => void finish(null) : advance}
            testID="onboarding-skip"
          />
        ) : null}
        {index > 0 ? (
          <Button
            label={t('onboarding.back')}
            variant="secondary"
            onPress={() => setIndex(index - 1)}
            testID="onboarding-back"
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  choice: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 10,
    minHeight: 44,
  },
  match: { borderWidth: 1, borderRadius: 8, padding: 12 },
});
