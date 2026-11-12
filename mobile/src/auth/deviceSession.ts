import { File, Paths } from 'expo-file-system';

import { useSessionStore } from './sessionStore';
import type { Me } from './types';

/**
 * What this device keeps about the signed-in traveller between launches (ADR-0033), so the app
 * still opens signed in on a poor or missing network: the last `Me`, and through the cleanups
 * registered here, queued messages and the chat cache. Everything is wiped when the session
 * really ends (sign-out, a revoked or expired session), never because a network request failed.
 */

const cleanups: (() => void)[] = [];

/** Run `cleanup` whenever the session ends on this device. */
export function onSessionEnded(cleanup: () => void): void {
  cleanups.push(cleanup);
}

/** The session is over: forget everything kept for it on this device. */
export function endDeviceSession(): void {
  for (const cleanup of cleanups) {
    try {
      cleanup();
    } catch {
      // One failing cleanup must not keep the others from running.
    }
  }
}

const meFile = () => new File(Paths.document, 'session-me.json');

/** The traveller last signed in on this device, when the session is still kept. */
export function readCachedMe(): Me | null {
  try {
    const file = meFile();
    if (!file.exists) return null;
    const me = JSON.parse(file.textSync()) as Me;
    return me?.account?.id && me.profile ? me : null;
  } catch {
    return null;
  }
}

function writeCachedMe(me: Me): void {
  try {
    meFile().writeSync(JSON.stringify(me));
  } catch {
    // Without the file the next offline launch starts signed out, as before.
  }
}

onSessionEnded(() => {
  const file = meFile();
  if (file.exists) file.delete();
});

// Keep the copy current: every `Me` the app learns (sign-in, refresh, settings) is saved.
useSessionStore.subscribe((state, previous) => {
  if (state.status === 'signed_in' && state.me && state.me !== previous.me) {
    writeCachedMe(state.me);
  }
});
