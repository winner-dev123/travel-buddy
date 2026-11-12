import { create } from 'zustand';

import type { RealtimeStatus } from './client';

/** Who is typing where: conversation id → user id → expiry (ms since epoch). */
type TypingMap = Record<string, Record<string, number>>;

interface RealtimeState {
  status: RealtimeStatus;
  typing: TypingMap;
  setStatus: (status: RealtimeStatus) => void;
  setTyping: (conversationId: string, userId: string, until: number | null) => void;
  /** Forget expired entries (the server's typing TTL is 8 s). */
  prune: (now: number) => void;
}

export const useRealtimeStore = create<RealtimeState>()((set) => ({
  status: 'idle',
  typing: {},
  setStatus: (status) => set({ status }),
  setTyping: (conversationId, userId, until) =>
    set((state) => {
      const current = { ...(state.typing[conversationId] ?? {}) };
      if (until === null) delete current[userId];
      else current[userId] = until;
      return { typing: { ...state.typing, [conversationId]: current } };
    }),
  prune: (now) =>
    set((state) => {
      let changed = false;
      const typing: TypingMap = {};
      for (const [conversationId, users] of Object.entries(state.typing)) {
        const alive = Object.fromEntries(Object.entries(users).filter(([, until]) => until > now));
        if (Object.keys(alive).length !== Object.keys(users).length) changed = true;
        typing[conversationId] = alive;
      }
      return changed ? { typing } : state;
    }),
}));

/** The users typing in a conversation right now (other than `me`). */
export function typingUsers(
  typing: TypingMap,
  conversationId: string,
  me: string | undefined,
  now: number,
): string[] {
  return Object.entries(typing[conversationId] ?? {})
    .filter(([user, until]) => user !== me && until > now)
    .map(([user]) => user);
}
