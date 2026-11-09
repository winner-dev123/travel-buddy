import type { ReactNode } from 'react';

/**
 * next-intl pattern: the real root layout (with <html>) is `app/[locale]/layout.tsx`.
 * This pass-through exists so that `app/not-found.tsx` has a layout.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return children;
}
