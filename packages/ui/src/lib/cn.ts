import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/** tailwind-merge must know our custom theme scales, or `text-display` would clash with colours. */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ['display', 'headline'],
      shadow: ['card', 'lift'],
      radius: ['card', 'pill'],
      ease: ['travel'],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
