// req: NFR-008
import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { i18n } from '@/i18n';
import { useSettingsStore } from '@/state/settingsStore';
import {
  chooseThemePreference,
  hydrateUiPreferences,
  readSavedThemePreference,
} from '@/state/uiPreferences';

import AppearanceScreen from '../app/settings/appearance';

jest.mock('expo-router', () => ({ Stack: { Screen: () => null } }));
// In-memory stand-in for the device file system.
jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const state = { failWrites: false };
  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts
        .map((part) => (typeof part === 'string' ? part : (part as { uri: string }).uri))
        .join('/');
    }
    get exists() {
      return files.has(this.uri);
    }
    textSync() {
      return files.get(this.uri) ?? '';
    }
    writeSync(text: string) {
      if (state.failWrites) throw new Error('disk full');
      files.set(this.uri, text);
    }
  }
  return { File, Paths: { document: { uri: 'doc' } }, mockFiles: files, mockState: state };
});

const fs = jest.requireMock<{
  mockFiles: Map<string, string>;
  mockState: { failWrites: boolean };
}>('expo-file-system');
const SAVED = 'doc/ui-preferences.json';

async function renderScreen() {
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <AppearanceScreen />
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  fs.mockFiles.clear();
  fs.mockState.failWrites = false;
  useSettingsStore.setState({ themePreference: 'dark' });
  await i18n.changeLanguage('en');
});

describe('appearance settings', () => {
  it('opens on dark, the default, and names every choice', async () => {
    await renderScreen();
    expect(screen.getByTestId('appearance-dark')).toBeSelected();
    expect(screen.getByTestId('appearance-light')).not.toBeSelected();
    expect(screen.getByTestId('appearance-system')).not.toBeSelected();
    expect(screen.getByText('Match this phone')).toBeTruthy();
    expect(screen.getByText('Your choice is kept on this phone.')).toBeTruthy();
  });

  it('applies a choice at once and remembers it for the next launch', async () => {
    await renderScreen();
    await fireEvent.press(screen.getByTestId('appearance-light'));
    expect(screen.getByTestId('appearance-light')).toBeSelected();
    expect(screen.getByTestId('appearance-dark')).not.toBeSelected();
    expect(useSettingsStore.getState().themePreference).toBe('light');
    expect(JSON.parse(fs.mockFiles.get(SAVED) ?? '{}')).toEqual({ theme: 'light' });

    // A fresh launch starts from the default and then reads the saved choice.
    useSettingsStore.setState({ themePreference: 'dark' });
    hydrateUiPreferences();
    expect(useSettingsStore.getState().themePreference).toBe('light');
  });

  it('is translated', async () => {
    await i18n.changeLanguage('de');
    await renderScreen();
    expect(screen.getByText('Dunkel')).toBeTruthy();
    expect(screen.getByText('Wie dieses Telefon')).toBeTruthy();
  });
});

describe('saved appearance', () => {
  it('keeps the default when nothing was saved', () => {
    expect(readSavedThemePreference()).toBeNull();
    hydrateUiPreferences();
    expect(useSettingsStore.getState().themePreference).toBe('dark');
  });

  it('ignores a damaged or unknown saved value', () => {
    fs.mockFiles.set(SAVED, '{not json');
    expect(readSavedThemePreference()).toBeNull();
    fs.mockFiles.set(SAVED, JSON.stringify({ theme: 'sepia' }));
    expect(readSavedThemePreference()).toBeNull();
    fs.mockFiles.set(SAVED, JSON.stringify({ theme: 'system' }));
    expect(readSavedThemePreference()).toBe('system');
  });

  it('still applies the choice when it cannot be written', () => {
    fs.mockState.failWrites = true;
    expect(() => chooseThemePreference('system')).not.toThrow();
    expect(useSettingsStore.getState().themePreference).toBe('system');
    expect(fs.mockFiles.has(SAVED)).toBe(false);
  });
});
