import { renderRouter, screen } from 'expo-router/testing-library';

import { i18n } from '@/i18n';
import { useSettingsStore } from '@/state/settingsStore';

// Real route files from app/, rendered through Expo Router's test harness.
import RootLayout from '../app/_layout';
import NotFound from '../app/+not-found';
import AuthLayout from '../app/(auth)/_layout';
import SignIn from '../app/(auth)/sign-in';
import OnboardingLayout from '../app/(onboarding)/_layout';
import Onboarding from '../app/(onboarding)/onboarding';
import TabsLayout from '../app/(tabs)/_layout';
import Companions from '../app/(tabs)/companions';
import Explore from '../app/(tabs)/explore';
import Home from '../app/(tabs)/index';
import Messages from '../app/(tabs)/messages';
import Profile from '../app/(tabs)/profile';

const routes = {
  _layout: RootLayout,
  '+not-found': NotFound,
  '(tabs)/_layout': TabsLayout,
  '(tabs)/index': Home,
  '(tabs)/explore': Explore,
  '(tabs)/companions': Companions,
  '(tabs)/messages': Messages,
  '(tabs)/profile': Profile,
  '(auth)/_layout': AuthLayout,
  '(auth)/sign-in': SignIn,
  '(onboarding)/_layout': OnboardingLayout,
  '(onboarding)/onboarding': Onboarding,
};

beforeEach(async () => {
  useSettingsStore.getState().setLocaleOverride(null);
  await i18n.changeLanguage('en');
});

describe('app navigation shell', () => {
  it('opens on Home with the five primary tabs', async () => {
    await renderRouter(routes, { initialUrl: '/' });

    expect(screen).toHavePathname('/');
    for (const label of ['Home', 'Explore', 'Companions', 'Messages', 'Profile']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByTestId('phase-placeholder-feed')).toBeTruthy();
    expect(screen.getByText('Coming in Phase 1')).toBeTruthy();
    expect(screen.getByText('3 planned capabilities')).toBeTruthy();
    expect(screen.getByText('Online only')).toBeTruthy();
  });

  it('shows discovery safety guidance on Companions without claiming safety', async () => {
    await renderRouter(routes, { initialUrl: '/companions' });

    expect(screen.getByText('Coming in Phase 2')).toBeTruthy();
    expect(screen.getByTestId('discovery-safety-notice')).toBeTruthy();
    expect(
      screen.getByText(
        'Traveler discovery is optional and off by default. We cannot guarantee that meeting someone you find here is safe.',
      ),
    ).toBeTruthy();
  });

  it('routes to the auth and onboarding placeholders', async () => {
    await renderRouter(routes, { initialUrl: '/sign-in' });
    expect(screen.getByTestId('phase-placeholder-auth')).toBeTruthy();

    await renderRouter(routes, { initialUrl: '/onboarding' });
    expect(screen.getByTestId('phase-placeholder-onboarding')).toBeTruthy();
    expect(screen.getByText('8. Traveler discovery (off by default)')).toBeTruthy();
  });

  it('applies the user locale override over the device locale', async () => {
    useSettingsStore.getState().setLocaleOverride('pt-BR');
    await renderRouter(routes, { initialUrl: '/messages' });

    expect(screen.getAllByText('Mensagens').length).toBeGreaterThan(0);
    expect(screen.getByText('Disponível na fase 3')).toBeTruthy();
  });
});
