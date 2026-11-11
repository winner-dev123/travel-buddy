import { renderHook } from '@testing-library/react-native';
import { SplashScreen } from 'expo-router';

import { useLaunchScreen } from '../launchScreen';

// The module under test calls the launch screen while it loads, so the mocks live in the factory.
jest.mock('expo-router', () => ({
  SplashScreen: {
    preventAutoHideAsync: jest.fn(() => Promise.resolve()),
    hide: jest.fn(),
  },
}));

const hide = jest.mocked(SplashScreen.hide);

describe('useLaunchScreen', () => {
  it('holds the launch screen from the moment the module loads', () => {
    expect(SplashScreen.preventAutoHideAsync).toHaveBeenCalledTimes(1);
  });

  it('keeps the launch screen while the app is not ready', async () => {
    hide.mockClear();
    await renderHook(() => useLaunchScreen(false));
    expect(hide).not.toHaveBeenCalled();
  });

  it('hides the launch screen once the app is ready', async () => {
    hide.mockClear();
    const { rerender } = await renderHook(
      ({ ready }: { ready: boolean }) => useLaunchScreen(ready),
      { initialProps: { ready: false } },
    );
    expect(hide).not.toHaveBeenCalled();
    await rerender({ ready: true });
    expect(hide).toHaveBeenCalledTimes(1);
  });
});
