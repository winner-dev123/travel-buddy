import mockNetInfo from '@react-native-community/netinfo/jest/netinfo-mock.js';

jest.mock('@react-native-community/netinfo', () => mockNetInfo);

jest.mock('expo-secure-store', () => {
  const store = new Map<string, string>();
  return {
    AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 0,
    getItemAsync: jest.fn(async (key: string) => store.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => {
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
      store.delete(key);
    }),
  };
});

jest.mock('expo-localization', () => {
  const locales = [{ languageTag: 'en-US', languageCode: 'en', regionCode: 'US' }];
  return {
    getLocales: () => locales,
    useLocales: () => locales,
  };
});

// Push notifications (expo-notifications): no native module in Jest; tests override as needed.
jest.mock('expo-notifications', () => ({
  AndroidImportance: { DEFAULT: 3 },
  setNotificationHandler: jest.fn(),
  getPermissionsAsync: jest.fn(async () => ({ granted: false, canAskAgain: true })),
  requestPermissionsAsync: jest.fn(async () => ({ granted: true })),
  getExpoPushTokenAsync: jest.fn(async () => ({ data: 'ExponentPushToken[test-token]' })),
  setNotificationChannelAsync: jest.fn(async () => null),
  addNotificationResponseReceivedListener: jest.fn(() => ({ remove: jest.fn() })),
}));

// Icons are glyphs from an icon font: rendered for real they add private-use characters to an
// element's text content. Every icon in the app is decorative (labels carry the meaning).
jest.mock('@expo/vector-icons/Ionicons', () => ({ __esModule: true, default: () => null }));

// The Companions map runs in a WebView (ADR-0030). The mock keeps the props on a View, so tests
// can fire page messages with `fireEvent(map, 'message', …)` and read what the app injected.
jest.mock('react-native-webview', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const { View } = jest.requireActual<typeof import('react-native')>('react-native');
  const injected: string[] = [];
  const WebView = React.forwardRef(function MockWebView(
    props: Record<string, unknown>,
    ref: React.Ref<unknown>,
  ) {
    React.useImperativeHandle(ref, () => ({
      injectJavaScript: (code: string) => injected.push(code),
      reload: () => undefined,
    }));
    return React.createElement(View, props);
  });
  return { __esModule: true, default: WebView, WebView, mockInjected: injected };
});
