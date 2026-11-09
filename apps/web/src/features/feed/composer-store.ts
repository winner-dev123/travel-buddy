'use client';

import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { DestinationSummary, PostKind, PostVisibility } from '@travelbuddy/domain-types';

/** Post composer draft, preserved per browser until published or discarded (brief §11). */
interface ComposerDraft {
  body: string;
  kind: PostKind;
  visibility: PostVisibility;
  /** `undefined` = not chosen yet (the composer falls back to the browse destination); `null` = removed on purpose. */
  destination?: Pick<DestinationSummary, 'id' | 'name' | 'path'> | null;
  setBody: (body: string) => void;
  setKind: (kind: PostKind) => void;
  setVisibility: (v: PostVisibility) => void;
  setDestination: (d: ComposerDraft['destination']) => void;
  reset: () => void;
}

const EMPTY = { body: '', kind: 'experience' as PostKind, visibility: 'followers' as PostVisibility, destination: undefined };

export const useComposerStore = create<ComposerDraft>()(
  persist(
    (set) => ({
      ...EMPTY,
      setBody: (body) => set({ body }),
      setKind: (kind) => set({ kind }),
      setVisibility: (visibility) => set({ visibility }),
      setDestination: (destination) => set({ destination }),
      reset: () => set(EMPTY),
    }),
    {
      name: 'tb-composer-draft',
      storage: createJSONStorage(() => {
        try {
          return localStorage;
        } catch {
          return sessionStorage;
        }
      }),
      partialize: ({ body, kind, visibility, destination }) => ({ body, kind, visibility, destination }),
    },
  ),
);
