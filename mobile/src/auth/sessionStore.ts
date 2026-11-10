import { create } from 'zustand';

import type { Me } from './types';

export type SessionStatus = 'restoring' | 'signed_out' | 'signed_in';

interface SessionState {
  status: SessionStatus;
  me: Me | null;
  /**
   * IdP token waiting for registration (age gate + consents). Kept in memory only, for the few
   * minutes of the registration form; it expires on its own.
   */
  pendingIdToken: string | null;
  /** Invitation link token opened while signed out; resumed after sign-in (memory only). */
  pendingInvite: string | null;
  setSignedIn: (me: Me) => void;
  setSignedOut: () => void;
  setMe: (me: Me) => void;
  setPendingIdToken: (token: string | null) => void;
  setPendingInvite: (token: string | null) => void;
}

export const useSessionStore = create<SessionState>()((set) => ({
  status: 'restoring',
  me: null,
  pendingIdToken: null,
  pendingInvite: null,
  setSignedIn: (me) => set({ status: 'signed_in', me, pendingIdToken: null }),
  setSignedOut: () =>
    set({ status: 'signed_out', me: null, pendingIdToken: null, pendingInvite: null }),
  setMe: (me) => set({ me }),
  setPendingIdToken: (token) => set({ pendingIdToken: token }),
  setPendingInvite: (token) => set({ pendingInvite: token }),
}));

/** Where to go once signed in: back to an invitation opened while signed out, else home. */
export function takeHomeRoute(): '/' | { pathname: '/invite'; params: { t: string } } {
  const invite = useSessionStore.getState().pendingInvite;
  if (!invite) return '/';
  useSessionStore.getState().setPendingInvite(null);
  return { pathname: '/invite', params: { t: invite } };
}
