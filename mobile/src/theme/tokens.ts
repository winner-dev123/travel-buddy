/**
 * Design tokens. Every colour pair that renders text or an essential UI
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
    background: '#FFFFFF',
    surface: '#F4F6F8',
    surfaceRaised: '#FFFFFF',
    textPrimary: '#0F172A',
    textSecondary: '#475569',
    primary: '#0A6C74',
    onPrimary: '#FFFFFF',
    danger: '#B42318',
    onDanger: '#FFFFFF',
    warningSurface: '#FFF4E5',
    onWarningSurface: '#7A4A00',
    successSurface: '#E8F5EE',
    onSuccessSurface: '#1E6B3A',
    infoSurface: '#E6F1FB',
    onInfoSurface: '#0B4F8A',
    divider: '#E2E8F0',
    borderStrong: '#7C8799',
    focusRing: '#1D4ED8',
    tabBarBackground: '#FFFFFF',
    tabBarActive: '#0A6C74',
    tabBarInactive: '#5B6577',
  },
  dark: {
    background: '#0B1220',
    surface: '#131C2E',
    surfaceRaised: '#1A2438',
    textPrimary: '#F1F5F9',
    textSecondary: '#A8B3C4',
    primary: '#5CC8D1',
    onPrimary: '#04262A',
    danger: '#F97066',
    onDanger: '#2B0A07',
    warningSurface: '#3A2A0A',
    onWarningSurface: '#FFD48A',
    successSurface: '#0F2E1D',
    onSuccessSurface: '#8FE0AE',
    infoSurface: '#0D2440',
    onInfoSurface: '#9CCBF5',
    divider: '#243049',
    borderStrong: '#6B7A93',
    focusRing: '#93B4FF',
    tabBarBackground: '#0F1726',
    tabBarActive: '#5CC8D1',
    tabBarInactive: '#9AA6B8',
  },
};

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
  { foreground: 'onDanger', background: 'danger', minRatio: 4.5 },
  { foreground: 'danger', background: 'background', minRatio: 4.5 },
  { foreground: 'onWarningSurface', background: 'warningSurface', minRatio: 4.5 },
  { foreground: 'onSuccessSurface', background: 'successSurface', minRatio: 4.5 },
  { foreground: 'onInfoSurface', background: 'infoSurface', minRatio: 4.5 },
  { foreground: 'tabBarActive', background: 'tabBarBackground', minRatio: 4.5 },
  { foreground: 'tabBarInactive', background: 'tabBarBackground', minRatio: 4.5 },
  { foreground: 'borderStrong', background: 'background', minRatio: 3 },
  { foreground: 'borderStrong', background: 'surface', minRatio: 3 },
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
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  pill: 999,
} as const;

/**
 * Type scale (px at 100 % system text size). React Native scales text with the
 * OS dynamic-type setting automatically; layouts must tolerate 200 %.
 */
export const typography = {
  caption: { fontSize: 12, lineHeight: 16, fontWeight: '400' },
  label: { fontSize: 14, lineHeight: 20, fontWeight: '600' },
  body: { fontSize: 16, lineHeight: 24, fontWeight: '400' },
  bodyStrong: { fontSize: 16, lineHeight: 24, fontWeight: '600' },
  title3: { fontSize: 18, lineHeight: 26, fontWeight: '600' },
  title2: { fontSize: 22, lineHeight: 28, fontWeight: '700' },
  title1: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  display: { fontSize: 34, lineHeight: 40, fontWeight: '700' },
} as const;

/** Elevation levels: Android `elevation` + iOS shadow equivalents. */
export const elevation = {
  0: { elevation: 0, shadowOpacity: 0, shadowRadius: 0, shadowOffset: { width: 0, height: 0 } },
  1: { elevation: 1, shadowOpacity: 0.08, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } },
  2: { elevation: 3, shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } },
  3: { elevation: 6, shadowOpacity: 0.16, shadowRadius: 12, shadowOffset: { width: 0, height: 4 } },
} as const;

/** Minimum interactive target (iOS HIG 44 pt; Android 48 dp is met via hitSlop). */
export const minTouchTarget = 44;

export interface Theme {
  scheme: ColorSchemeName;
  colors: ColorTokens;
  spacing: typeof spacing;
  radii: typeof radii;
  typography: typeof typography;
  elevation: typeof elevation;
  minTouchTarget: number;
}

export function buildTheme(scheme: ColorSchemeName): Theme {
  return {
    scheme,
    colors: colors[scheme],
    spacing,
    radii,
    typography,
    elevation,
    minTouchTarget,
  };
}
