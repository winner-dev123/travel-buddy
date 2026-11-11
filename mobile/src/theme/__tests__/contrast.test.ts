// req: NFR-008
import { contrastRatio, relativeLuminance } from '../contrast';
import { accentGradient, colors, contrastPairs, scrims, type ColorSchemeName } from '../tokens';
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

  it.each([0, 1] as const)('button text meets 4.5:1 on accent gradient stop %d', (stop) => {
    const ratio = contrastRatio(colors[scheme].onPrimary, accentGradient[scheme][stop]);
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it('defines the same token set as the light theme', () => {
    expect(Object.keys(colors[scheme]).sort()).toEqual(Object.keys(colors.light).sort());
  });
});

describe('text on photos', () => {
  /** `rgba(r,g,b,a)` painted over an opaque hex colour, as a hex colour. */
  function over(rgba: string, backdrop: string): string {
    const [r, g, b, a] = (rgba.match(/[\d.]+/g) ?? []).map(Number) as [
      number,
      number,
      number,
      number,
    ];
    const under = [1, 3, 5].map((at) => parseInt(backdrop.slice(at, at + 2), 16));
    return `#${[r, g, b]
      .map((channel, index) => Math.round(channel * a + (under[index] ?? 0) * (1 - a)))
      .map((channel) => channel.toString(16).padStart(2, '0'))
      .join('')}`;
  }

  // A pure white photo is the worst case for white text.
  it('stays readable on a chip over the brightest photo', () => {
    const chip = over(scrims.photoChip, '#FFFFFF');
    expect(contrastRatio(scrims.onPhoto, chip)).toBeGreaterThanOrEqual(4.5);
  });

  it('stays readable at the foot of the caption scrim over the brightest photo', () => {
    const foot = over(scrims.photo[1], '#FFFFFF');
    expect(contrastRatio(scrims.onPhoto, foot)).toBeGreaterThanOrEqual(4.5);
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
