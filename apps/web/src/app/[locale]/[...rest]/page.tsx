import { notFound } from 'next/navigation';

/** Catch-all so unknown localized paths render the localized not-found page (next-intl pattern). */
export default function CatchAll() {
  notFound();
}
