// req: DISC-004, DISC-012
import {
  layoutPins,
  MAX_PUSH_M,
  SEPARATION_M,
  SPREAD_M,
  stableHash,
  type PlacedTraveller,
} from '../pinLayout';

const helsinki = { lat: 60.1699, lng: 24.9384 };
const kallio = { lat: 60.1841, lng: 24.9497 };
const centres = new Map([
  ['city', helsinki],
  ['area', kallio],
]);

function metres(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const y = (a.lat - b.lat) * 111_320;
  const x = (a.lng - b.lng) * 111_320 * Math.cos((b.lat * Math.PI) / 180);
  return Math.hypot(x, y);
}

const inCity = (id: string): PlacedTraveller => ({ id, anchorId: 'city', anchorKind: 'city' });
const inArea = (id: string): PlacedTraveller => ({
  id,
  anchorId: 'area',
  anchorKind: 'neighborhood',
});

describe('pin layout', () => {
  it('spreads each traveller around the public centre of the area they share', () => {
    const travellers = [
      ...Array.from({ length: 8 }, (_, i) => inCity(`c${i}`)),
      inArea('n1'),
      inArea('n2'),
    ];
    const placed = layoutPins(travellers, centres);
    expect(placed.size).toBe(10);
    for (const traveller of travellers) {
      const at = placed.get(traveller.id)!;
      const centre = traveller.anchorKind === 'city' ? helsinki : kallio;
      const spread = SPREAD_M[traveller.anchorKind];
      const distance = metres(at, centre);
      expect(distance).toBeGreaterThanOrEqual(spread.min - 1);
      expect(distance).toBeLessThanOrEqual(spread.max + MAX_PUSH_M[traveller.anchorKind] + 1);
    }
  });

  it('keeps pins apart', () => {
    const placed = [
      ...layoutPins(
        Array.from({ length: 12 }, (_, i) => inCity(`t${i}`)),
        centres,
      ).values(),
    ];
    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        expect(metres(placed[i]!, placed[j]!)).toBeGreaterThan(250);
      }
    }
  });

  it('pushes apart pins of a city and a neighbourhood near its centre', () => {
    // The staging demo: three travellers sharing Helsinki, two sharing Kallio, 1.6 km away.
    const travellers = [
      inCity('mika'),
      inCity('lucas'),
      inCity('thabo'),
      inArea('sofia'),
      inArea('priya'),
    ];
    const placed = [...layoutPins(travellers, centres).values()];
    for (let i = 0; i < placed.length; i += 1) {
      for (let j = i + 1; j < placed.length; j += 1) {
        expect(metres(placed[i]!, placed[j]!)).toBeGreaterThanOrEqual(SEPARATION_M - 1);
      }
    }
  });

  it('depends only on who is there, not on the order results arrive in', () => {
    const travellers = ['a', 'b', 'c', 'd'].map(inCity);
    const first = layoutPins(travellers, centres);
    const shuffled = layoutPins([...travellers].reverse(), centres);
    for (const { id } of travellers) expect(shuffled.get(id)).toEqual(first.get(id));
  });

  it('leaves out travellers whose area centre is unknown', () => {
    const placed = layoutPins(
      [inCity('a'), { id: 'b', anchorId: 'x', anchorKind: 'city' }],
      centres,
    );
    expect([...placed.keys()]).toEqual(['a']);
  });

  it('hashes stably', () => {
    expect(stableHash('')).toBe(0x811c9dc5);
    expect(stableHash('u2')).toBe(stableHash('u2'));
    expect(stableHash('u2')).not.toBe(stableHash('u3'));
  });
});
