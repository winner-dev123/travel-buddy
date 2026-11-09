'use client';

import { useMemo, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Check, LocateFixed, MapPin, UsersRound } from 'lucide-react';
import { isApiError } from '@travelbuddy/api-client';
import { TRAVEL_STYLES, type DestinationSummary, type TravelStyle } from '@travelbuddy/domain-types';
import { LOCALES, type LocaleCode } from '@travelbuddy/i18n';
import { displayNameSchema } from '@travelbuddy/validation';
import { Alert, Button, Card, FormField, Input, NativeSelect, Switch, Textarea, ToggleChip, cn } from '@travelbuddy/ui';
import { DestinationSearch } from '@/components/destination-search';
import { browserApi } from '@/lib/api-browser';
import { countryOptions } from '@/lib/countries';
import { localizedPath } from '@/lib/paths';
import { setFeedLocationPreference } from '@/features/feed/location-preference';

type StepId = 'profile' | 'language' | 'interests' | 'home' | 'destination' | 'location' | 'discovery';
const STEPS: StepId[] = ['profile', 'language', 'interests', 'home', 'destination', 'location', 'discovery'];
const ESSENTIAL: StepId[] = ['profile'];

export interface OnboardingInitial {
  displayName: string;
  bio: string | null;
  uiLocale: LocaleCode;
  travelStyles: TravelStyle[];
  homeCountry: string | null;
  browseDestination: DestinationSummary | null;
}

/**
 * Seven-step onboarding (brief §8). Everything except the display name can be skipped. Nearby
 * people discovery is OFF unless the user turns it on here or later in settings.
 */
export function OnboardingFlow({ initial }: { initial: OnboardingInitial }) {
  const t = useTranslations('onboarding');
  const ts = useTranslations('travelStyles');
  const locale = useLocale();
  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState(initial.displayName);
  const [bio, setBio] = useState(initial.bio ?? '');
  const [uiLocale, setUiLocale] = useState<LocaleCode>(initial.uiLocale);
  const [styles, setStyles] = useState<TravelStyle[]>(initial.travelStyles);
  const [homeCountry, setHomeCountry] = useState<string>(initial.homeCountry ?? '');
  const [destination, setDestination] = useState<DestinationSummary | null>(initial.browseDestination);
  const [useLocation, setUseLocation] = useState(false);
  const [locationState, setLocationState] = useState<'idle' | 'granted' | 'denied' | 'unsupported'>('idle');
  const [discovery, setDiscovery] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const countries = useMemo(() => countryOptions(locale), [locale]);

  const current = STEPS[step] as StepId;
  const isLast = step === STEPS.length - 1;

  const next = () => {
    if (current === 'profile') {
      const parsed = displayNameSchema.safeParse(displayName);
      if (!parsed.success) {
        setNameError(t('profile.nameRequired'));
        return;
      }
      setNameError(null);
    }
    if (isLast) void finish();
    else setStep((s) => s + 1);
  };

  const requestLocation = () => {
    if (!('geolocation' in navigator)) {
      setLocationState('unsupported');
      return;
    }
    // Asking here only triggers the browser permission prompt. No coordinates are sent or stored.
    navigator.geolocation.getCurrentPosition(
      () => {
        setLocationState('granted');
        setUseLocation(true);
      },
      () => {
        setLocationState('denied');
        setUseLocation(false);
      },
      { maximumAge: 600_000, timeout: 10_000, enableHighAccuracy: false },
    );
  };

  async function finish() {
    setSaving(true);
    setSaveError(null);
    const api = browserApi();
    try {
      await api.me.update({
        display_name: displayName.trim(),
        bio: bio.trim() || null,
        travel_styles: styles,
        home_country_code: homeCountry || null,
      });
      if (uiLocale !== initial.uiLocale) await api.me.updatePreferences({ ui_locale: uiLocale });
      if (destination && destination.id !== initial.browseDestination?.id) await api.me.setBrowseDestination(destination.id);
      if (discovery) await api.me.updatePrivacy({ discovery_enabled: true });
      setFeedLocationPreference(useLocation);
      await api.me.completeOnboarding();
      window.location.assign(localizedPath(uiLocale, '/feed'));
    } catch (error) {
      setSaving(false);
      setSaveError(isApiError(error) && error.requestId ? t('saveErrorRef', { id: error.requestId }) : t('saveError'));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <p className="text-sm font-semibold text-primary">{t('progress', { current: step + 1, total: STEPS.length })}</p>
        <div className="flex gap-1.5" aria-hidden="true">
          {STEPS.map((s, i) => (
            <span key={s} className={cn('h-1.5 flex-1 rounded-full', i <= step ? 'bg-primary' : 'bg-surface-muted')} />
          ))}
        </div>
        <h1 className="font-display text-3xl font-semibold">{t(`${current}.title`)}</h1>
        <p className="text-muted-foreground">{t(`${current}.subtitle`)}</p>
      </div>

      <Card className="flex flex-col gap-5 p-6">
        {current === 'profile' ? (
          <>
            <FormField id="ob-name" label={t('profile.name')} error={nameError ?? undefined} required>
              <Input value={displayName} maxLength={50} autoComplete="nickname" onChange={(e) => setDisplayName(e.target.value)} />
            </FormField>
            <FormField id="ob-bio" label={t('profile.bio')} hint={t('profile.bioHint')}>
              <Textarea value={bio} maxLength={300} onChange={(e) => setBio(e.target.value)} />
            </FormField>
          </>
        ) : null}

        {current === 'language' ? (
          <div role="radiogroup" aria-label={t('language.title')} className="grid gap-2 sm:grid-cols-2">
            {LOCALES.map((l) => (
              <button
                key={l.code}
                type="button"
                role="radio"
                aria-checked={uiLocale === l.code}
                onClick={() => setUiLocale(l.code)}
                lang={l.bcp47}
                className={cn(
                  'flex items-center justify-between rounded-2xl border px-4 py-3 text-start font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  uiLocale === l.code ? 'border-primary bg-primary-soft' : 'border-border hover:border-primary/50',
                )}
              >
                {l.label}
                {uiLocale === l.code ? <Check className="size-4 text-primary" aria-hidden="true" /> : null}
              </button>
            ))}
          </div>
        ) : null}

        {current === 'interests' ? (
          <div className="flex flex-wrap gap-2" role="group" aria-label={t('interests.title')}>
            {TRAVEL_STYLES.map((s) => (
              <ToggleChip key={s} pressed={styles.includes(s)} onClick={() => setStyles((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]))}>
                {ts(s)}
              </ToggleChip>
            ))}
          </div>
        ) : null}

        {current === 'home' ? (
          <FormField id="ob-country" label={t('home.label')} hint={t('home.hint')}>
            <NativeSelect value={homeCountry} onChange={(e) => setHomeCountry(e.target.value)}>
              <option value="">{t('home.none')}</option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        ) : null}

        {current === 'destination' ? (
          <div className="flex flex-col gap-3">
            <DestinationSearch label={t('destination.label')} onSelect={setDestination} />
            {destination ? (
              <p className="flex items-center gap-2 text-sm">
                <MapPin className="size-4 text-primary" aria-hidden="true" />
                {t('destination.selected', { name: destination.name })}
              </p>
            ) : null}
          </div>
        ) : null}

        {current === 'location' ? (
          <div className="flex flex-col gap-4">
            <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
              <li>• {t('location.p1')}</li>
              <li>• {t('location.p2')}</li>
              <li>• {t('location.p3')}</li>
            </ul>
            <Button type="button" variant={locationState === 'granted' ? 'soft' : 'primary'} onClick={requestLocation} disabled={locationState === 'granted'}>
              <LocateFixed aria-hidden="true" />
              {locationState === 'granted' ? t('location.granted') : t('location.allow')}
            </Button>
            {locationState === 'denied' ? <Alert tone="info">{t('location.denied')}</Alert> : null}
            {locationState === 'unsupported' ? <Alert tone="info">{t('location.unsupported')}</Alert> : null}
          </div>
        ) : null}

        {current === 'discovery' ? (
          <div className="flex flex-col gap-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex gap-3">
                <UsersRound className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
                <label htmlFor="ob-discovery" className="flex flex-col">
                  <span className="font-semibold">{t('discovery.toggle')}</span>
                  <span className="text-sm text-muted-foreground">{t('discovery.toggleHint')}</span>
                </label>
              </div>
              <Switch id="ob-discovery" checked={discovery} onCheckedChange={setDiscovery} />
            </div>
            <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
              <li>• {t('discovery.p1')}</li>
              <li>• {t('discovery.p2')}</li>
              <li>• {t('discovery.p3')}</li>
            </ul>
          </div>
        ) : null}
      </Card>

      {saveError ? <Alert tone="danger">{saveError}</Alert> : null}

      <div className="flex items-center justify-between gap-3">
        <Button type="button" variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || saving}>
          {t('back')}
        </Button>
        <div className="flex gap-2">
          {!ESSENTIAL.includes(current) && !isLast ? (
            <Button type="button" variant="secondary" onClick={() => setStep((s) => s + 1)} disabled={saving}>
              {t('skip')}
            </Button>
          ) : null}
          <Button type="button" onClick={next} loading={saving}>
            {isLast ? t('finish') : t('next')}
          </Button>
        </div>
      </div>
    </div>
  );
}
