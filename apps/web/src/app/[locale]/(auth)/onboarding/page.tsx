import { redirect } from 'next/navigation';
import { setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { isLocale } from '@travelbuddy/i18n';
import { OnboardingFlow } from '@/features/onboarding/onboarding-flow';
import { localizedPath } from '@/lib/paths';
import { getMe } from '@/server/viewer';

export const dynamic = 'force-dynamic';

export default async function OnboardingPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const me = await getMe(locale);
  if (me.onboarding_completed) redirect(localizedPath(locale, '/feed'));
  return (
    <OnboardingFlow
      initial={{
        displayName: me.profile.display_name,
        bio: me.profile.bio,
        uiLocale: isLocale(me.preferences.ui_locale) ? me.preferences.ui_locale : locale,
        travelStyles: me.profile.travel_styles,
        homeCountry: me.profile.home_country_code,
        browseDestination: me.browse_destination,
      }}
    />
  );
}
