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
