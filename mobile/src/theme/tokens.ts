/**
 * Design tokens: the "Noir" look. Obsidian surfaces, ivory text and one champagne-gold accent;
 * serif titles (Playfair Display) over a geometric sans (Manrope). Dark is the default theme
 * (docs/03 §10); light is the same system on ivory with a bronze accent.
 *
 * Every colour pair that renders text or an essential UI
 * boundary is verified for WCAG 2.2 AA contrast in `__tests__/contrast.test.ts`:
 *   - text pairs: ≥ 4.5:1 (1.4.3)
 *   - non-text UI boundaries (input outlines, focus rings): ≥ 3:1 (1.4.11)
 * If you add a colour, add its pair to `contrastPairs` below.
 */

export type ColorSchemeName = 'light' | 'dark';

export interface ColorTokens {
  background: string;
  surface: string;
  surfaceRaised: string;
  textPrimary: string;
  textSecondary: string;
  primary: string;
  onPrimary: string;
  /** A quiet tint of the accent: selected chips, icon wells, badges. */
  primaryMuted: string;
  onPrimaryMuted: string;
  danger: string;
  onDanger: string;
  warningSurface: string;
  onWarningSurface: string;
  successSurface: string;
  onSuccessSurface: string;
  infoSurface: string;
  onInfoSurface: string;
  /** Decorative dividers only — not contrast-tested, never the sole affordance. */
  divider: string;
  /** Input outlines and other essential boundaries (≥ 3:1). */
  borderStrong: string;
  focusRing: string;
  tabBarBackground: string;
  tabBarActive: string;
  tabBarInactive: string;
}

export const colors: Record<ColorSchemeName, ColorTokens> = {
  light: {
    background: '#FAF8F4',
    surface: '#F2EEE6',
    surfaceRaised: '#FFFFFF',
    textPrimary: '#17140E',
    textSecondary: '#5F5A4F',
    primary: '#7A5910',
    onPrimary: '#FFFFFF',
    primaryMuted: '#F3E8CC',
    onPrimaryMuted: '#5A4108',
    danger: '#B42318',
    onDanger: '#FFFFFF',
    warningSurface: '#FBEFD9',
    onWarningSurface: '#734700',
    successSurface: '#E4F2E9',
    onSuccessSurface: '#1D6537',
    infoSurface: '#E8ECF6',
    onInfoSurface: '#2B4375',
    divider: '#E5DFD3',
    borderStrong: '#857E70',
    focusRing: '#1D4ED8',
    tabBarBackground: '#FFFFFF',
    tabBarActive: '#7A5910',
    tabBarInactive: '#6A6558',
  },
  dark: {
    background: '#0B0B0D',
    surface: '#131316',
    surfaceRaised: '#1B1B20',
    textPrimary: '#F4F1EA',
    textSecondary: '#A9A59C',
    primary: '#D9B56C',
    onPrimary: '#1B1404',
    primaryMuted: '#2B2413',
    onPrimaryMuted: '#EBD197',
    danger: '#F2857B',
    onDanger: '#2B0A07',
    warningSurface: '#33260B',
    onWarningSurface: '#F5CE85',
    successSurface: '#10291C',
    onSuccessSurface: '#8FDDB0',
    infoSurface: '#1A2030',
    onInfoSurface: '#B8C8EE',
    divider: '#27272D',
    borderStrong: '#77757D',
    focusRing: '#F1DCA8',
    tabBarBackground: '#0E0E11',
    tabBarActive: '#D9B56C',
    tabBarInactive: '#96928A',
  },
};

/**
 * Accent gradient for the main call to action (left to right), per scheme. Text on it uses
 * `onPrimary`; both stops are contrast-tested in `__tests__/contrast.test.ts`.
 */
export const accentGradient: Record<ColorSchemeName, readonly [string, string]> = {
  light: ['#8A6614', '#6B4D0C'],
  dark: ['#E8CB8A', '#C9A255'],
};

/** Scrims over photos. Text on a photo is always `onPhoto`: photos ignore the theme. */
export const scrims = {
  /** Behind modal sheets. */
  backdrop: 'rgba(0,0,0,0.6)',
  /** Bottom of a photo, under a caption: transparent to this. */
  photo: ['rgba(0,0,0,0)', 'rgba(0,0,0,0.72)'] as const,
  /** A solid chip on a photo. */
  photoChip: 'rgba(11,11,13,0.72)',
  onPhoto: '#FFFFFF',
} as const;

type ColorKey = keyof ColorTokens;

export interface ContrastPair {
  foreground: ColorKey;
  background: ColorKey;
  /** Minimum ratio: 4.5 for text, 3 for non-text UI boundaries. */
  minRatio: 4.5 | 3;
}

/** Pairs that must meet WCAG AA in every colour scheme. */
export const contrastPairs: readonly ContrastPair[] = [
  { foreground: 'textPrimary', background: 'background', minRatio: 4.5 },
  { foreground: 'textPrimary', background: 'surface', minRatio: 4.5 },
  { foreground: 'textPrimary', background: 'surfaceRaised', minRatio: 4.5 },
  { foreground: 'textSecondary', background: 'background', minRatio: 4.5 },
  { foreground: 'textSecondary', background: 'surface', minRatio: 4.5 },
  { foreground: 'textSecondary', background: 'surfaceRaised', minRatio: 4.5 },
  { foreground: 'onPrimary', background: 'primary', minRatio: 4.5 },
  { foreground: 'primary', background: 'background', minRatio: 4.5 },
  { foreground: 'primary', background: 'surface', minRatio: 4.5 },
  { foreground: 'primary', background: 'surfaceRaised', minRatio: 4.5 },
  { foreground: 'onPrimaryMuted', background: 'primaryMuted', minRatio: 4.5 },
  { foreground: 'textPrimary', background: 'primaryMuted', minRatio: 4.5 },
  { foreground: 'onDanger', background: 'danger', minRatio: 4.5 },
  { foreground: 'danger', background: 'background', minRatio: 4.5 },
  { foreground: 'danger', background: 'surfaceRaised', minRatio: 4.5 },
  { foreground: 'onWarningSurface', background: 'warningSurface', minRatio: 4.5 },
  { foreground: 'onSuccessSurface', background: 'successSurface', minRatio: 4.5 },
  { foreground: 'onInfoSurface', background: 'infoSurface', minRatio: 4.5 },
  { foreground: 'tabBarActive', background: 'tabBarBackground', minRatio: 4.5 },
  { foreground: 'tabBarInactive', background: 'tabBarBackground', minRatio: 4.5 },
  { foreground: 'borderStrong', background: 'background', minRatio: 3 },
  { foreground: 'borderStrong', background: 'surface', minRatio: 3 },
  { foreground: 'borderStrong', background: 'surfaceRaised', minRatio: 3 },
  { foreground: 'focusRing', background: 'background', minRatio: 3 },
];

/** 4-pt spacing grid. Use `spacing[n]` = n × 4 px. */
export const spacing = {
  0: 0,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
} as const;

export const radii = {
  sm: 6,
  md: 12,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

/**
 * Font families, registered at startup by `theme/fonts.ts` under these exact names. Each file is
 * one weight, so styles pick a family and never set `fontWeight` (Android would fake the bold).
 */
export const fontFamilies = {
  serif: 'PlayfairDisplay_600SemiBold',
  serifBold: 'PlayfairDisplay_700Bold',
  regular: 'Manrope_400Regular',
  medium: 'Manrope_500Medium',
  semibold: 'Manrope_600SemiBold',
  bold: 'Manrope_700Bold',
} as const;

/**
 * Type scale (px at 100 % system text size). React Native scales text with the
 * OS dynamic-type setting automatically; layouts must tolerate 200 %.
 */
export const typography = {
  /** Small capitals above a title ("eyebrow"). Pair with `textTransform: 'uppercase'`. */
  overline: { fontSize: 11, lineHeight: 16, fontFamily: fontFamilies.bold, letterSpacing: 1.6 },
  caption: { fontSize: 12, lineHeight: 16, fontFamily: fontFamilies.medium, letterSpacing: 0.1 },
  label: { fontSize: 14, lineHeight: 20, fontFamily: fontFamilies.semibold, letterSpacing: 0.1 },
  body: { fontSize: 16, lineHeight: 24, fontFamily: fontFamilies.regular },
  bodyStrong: { fontSize: 16, lineHeight: 24, fontFamily: fontFamilies.semibold },
  title3: { fontSize: 18, lineHeight: 26, fontFamily: fontFamilies.bold, letterSpacing: -0.1 },
  title2: { fontSize: 22, lineHeight: 30, fontFamily: fontFamilies.serif },
  title1: { fontSize: 30, lineHeight: 38, fontFamily: fontFamilies.serifBold },
  display: { fontSize: 38, lineHeight: 46, fontFamily: fontFamilies.serifBold },
} as const;

/** Elevation levels: Android `elevation` + iOS shadow equivalents. */
export const elevation = {
  0: { elevation: 0, shadowOpacity: 0, shadowRadius: 0, shadowOffset: { width: 0, height: 0 } },
  1: { elevation: 1, shadowOpacity: 0.1, shadowRadius: 3, shadowOffset: { width: 0, height: 1 } },
  2: { elevation: 4, shadowOpacity: 0.18, shadowRadius: 10, shadowOffset: { width: 0, height: 4 } },
  3: { elevation: 8, shadowOpacity: 0.28, shadowRadius: 20, shadowOffset: { width: 0, height: 8 } },
} as const;

/** Minimum interactive target (iOS HIG 44 pt; Android 48 dp is met via hitSlop). */
export const minTouchTarget = 44;

export interface Theme {
  scheme: ColorSchemeName;
  colors: ColorTokens;
  accentGradient: readonly [string, string];
  spacing: typeof spacing;
  radii: typeof radii;
  typography: typeof typography;
  fonts: typeof fontFamilies;
  elevation: typeof elevation;
  minTouchTarget: number;
}

export function buildTheme(scheme: ColorSchemeName): Theme {
  return {
    scheme,
    colors: colors[scheme],
    accentGradient: accentGradient[scheme],
    spacing,
    radii,
    typography,
    fonts: fontFamilies,
    elevation,
    minTouchTarget,
  };
}
