import { SplashScreen } from 'expo-router';
import { useEffect } from 'react';

// Keep the native launch screen up until the app says it is ready. Without this the router
// hides it on the first frame, before the typefaces are registered. A no-op where there is no
// native launch screen (tests, web).
void SplashScreen.preventAutoHideAsync();

/**
 * Hides the launch screen once `ready` is true, so the first frame the traveller sees is the
 * finished one. `ready` must become true on failure paths too, or the app never opens.
 */
export function useLaunchScreen(ready: boolean): void {
  useEffect(() => {
    if (ready) {
      SplashScreen.hide();
    }
  }, [ready]);
}
