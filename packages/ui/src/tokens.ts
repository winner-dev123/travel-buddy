/**
 * Design tokens as plain values for non-CSS consumers (React Native, charts, OG images).
 * Must stay in sync with tokens.css — a unit test compares them.
 */
export const colors = {
  light: {
    background: '#fafaf7',
    surface: '#ffffff',
    surfaceMuted: '#f1f4f0',
    foreground: '#17252a',
    mutedForeground: '#5f6d71',
    slate: '#69777b',
    border: '#e2e7e3',
    primary: '#087f8c',
    primaryForeground: '#ffffff',
    secondary: '#15b8a6',
    secondaryForeground: '#17252a',
    accent: '#ff735c',
    accentForeground: '#17252a',
    danger: '#c2362b',
    success: '#1e7f4f',
  },
  dark: {
    background: '#0e1a1d',
    surface: '#142429',
    surfaceMuted: '#1a2e34',
    foreground: '#ecf2f1',
    mutedForeground: '#9db0b3',
    slate: '#8a9c9f',
    border: '#243a40',
    primary: '#2fb3bf',
    primaryForeground: '#0e1a1d',
    secondary: '#2dd4bf',
    secondaryForeground: '#0e1a1d',
    accent: '#ff8a75',
    accentForeground: '#17252a',
    danger: '#f07167',
    success: '#4cc38a',
  },
} as const;

/** Brand palette exactly as specified in the product brief (§5). */
export const brand = {
  oceanBlue: '#087F8C',
  tropicalTeal: '#15B8A6',
  sunsetCoral: '#FF735C',
  warmBackground: '#FAFAF7',
  primaryText: '#17252A',
  secondaryText: '#69777B',
  white: '#FFFFFF',
} as const;

export const spacing = { 0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48, 16: 64, 20: 80, 24: 96 } as const;
export const radii = { sm: 6, md: 10, lg: 14, card: 20, pill: 999 } as const;
export const breakpoints = { sm: 640, md: 768, lg: 1024, xl: 1280, '2xl': 1536 } as const;
export const motion = {
  durationFast: 120,
  durationBase: 200,
  durationSlow: 320,
  easeTravel: 'cubic-bezier(0.22, 1, 0.36, 1)',
} as const;
export const typography = {
  display: 'Fraunces',
  sans: 'Plus Jakarta Sans',
} as const;
