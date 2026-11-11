import { Manrope_400Regular } from '@expo-google-fonts/manrope/400Regular';
import { Manrope_500Medium } from '@expo-google-fonts/manrope/500Medium';
import { Manrope_600SemiBold } from '@expo-google-fonts/manrope/600SemiBold';
import { Manrope_700Bold } from '@expo-google-fonts/manrope/700Bold';
import { PlayfairDisplay_600SemiBold } from '@expo-google-fonts/playfair-display/600SemiBold';
import { PlayfairDisplay_700Bold } from '@expo-google-fonts/playfair-display/700Bold';
import { useFonts } from 'expo-font';

import { fontFamilies } from './tokens';

type FontFamilyName = (typeof fontFamilies)[keyof typeof fontFamilies];

/**
 * The app's typefaces (both SIL Open Font License), keyed by the family names the tokens use.
 * The `Record` type keeps this map and `fontFamilies` in step: a new family must be loaded here.
 */
export const appFonts: Record<FontFamilyName, number> = {
  PlayfairDisplay_600SemiBold,
  PlayfairDisplay_700Bold,
  Manrope_400Regular,
  Manrope_500Medium,
  Manrope_600SemiBold,
  Manrope_700Bold,
};

/**
 * True once the typefaces are registered, or loading failed: text then falls back to the system
 * font, which is better than an app that never opens.
 */
export function useAppFonts(): boolean {
  const [loaded, error] = useFonts(appFonts);
  return loaded || error !== null;
}
