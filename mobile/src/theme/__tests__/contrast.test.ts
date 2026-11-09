// req: NFR-008
import { contrastRatio, relativeLuminance } from '../contrast';
import { colors, contrastPairs, type ColorSchemeName } from '../tokens';
import { resolveColorScheme } from '../useAppTheme';

describe('contrastRatio', () => {
  it('matches WCAG reference values', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5);
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5);
    // #767676 on white is the classic 4.54:1 minimum-AA grey.
    expect(contrastRatio('#767676', '#FFFFFF')).toBeCloseTo(4.54, 2);
    expect(relativeLuminance('#FFFFFF')).toBeCloseTo(1, 5);
  });

  it('is symmetric and rejects malformed colours', () => {
    expect(contrastRatio('#0A6C74', '#FFFFFF')).toBeCloseTo(contrastRatio('#FFFFFF', '#0A6C74'));
    expect(() => contrastRatio('red', '#FFFFFF')).toThrow();
    expect(() => contrastRatio('#FFF', '#FFFFFF')).toThrow();
  });
});

describe.each<ColorSchemeName>(['light', 'dark'])('%s theme', (scheme) => {
  it.each(contrastPairs.map((pair) => [pair.foreground, pair.background, pair.minRatio] as const))(
    '%s on %s meets %d:1',
    (foreground, background, minRatio) => {
      const ratio = contrastRatio(colors[scheme][foreground], colors[scheme][background]);
      expect(ratio).toBeGreaterThanOrEqual(minRatio);
    },
  );

  it('defines the same token set as the light theme', () => {
    expect(Object.keys(colors[scheme]).sort()).toEqual(Object.keys(colors.light).sort());
  });
});

describe('resolveColorScheme', () => {
  it('honours an explicit preference over the OS', () => {
    expect(resolveColorScheme('dark', 'light')).toBe('dark');
    expect(resolveColorScheme('light', 'dark')).toBe('light');
  });

  it('follows the OS for "system", defaulting to light', () => {
    expect(resolveColorScheme('system', 'dark')).toBe('dark');
    expect(resolveColorScheme('system', 'light')).toBe('light');
    expect(resolveColorScheme('system', null)).toBe('light');
  });
});
