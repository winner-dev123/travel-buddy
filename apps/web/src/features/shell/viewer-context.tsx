'use client';

import { createContext, useContext, type ReactNode } from 'react';
import type { ViewerSummary } from '@/server/viewer';

const ViewerContext = createContext<ViewerSummary | null>(null);

export function ViewerProvider({ viewer, children }: { viewer: ViewerSummary; children: ReactNode }) {
  return <ViewerContext.Provider value={viewer}>{children}</ViewerContext.Provider>;
}

/** The signed-in viewer (traveler/admin areas only). Contains no tokens. */
export function useViewer(): ViewerSummary {
  const v = useContext(ViewerContext);
  if (!v) throw new Error('useViewer must be used inside the traveler shell');
  return v;
}
