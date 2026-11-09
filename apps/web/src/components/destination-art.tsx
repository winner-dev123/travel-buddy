import { cn } from '@travelbuddy/ui';

/**
 * Deterministic branded artwork used wherever licensed photography is missing (docs/web/01 §14).
 * The same seed always yields the same "travel poster", so placeholders are stable and never
 * pretend to be a photo of the place.
 */
const PALETTES = [
  { sky: ['#ffd6c7', '#ff9d85', '#ff735c'], sun: '#fff4e6', layers: ['#0f8f9b', '#087f8c', '#05606a'] },
  { sky: ['#c9f4ec', '#7fdccd', '#15b8a6'], sun: '#ffffff', layers: ['#11a394', '#087f8c', '#0a5b63'] },
  { sky: ['#2b3a67', '#6b4e9b', '#ff8a75'], sun: '#ffd3a8', layers: ['#3a2f5b', '#271f42', '#17142b'] },
  { sky: ['#ffe8c2', '#f6b26b', '#e07a5f'], sun: '#fff8ec', layers: ['#c0603f', '#9c4a2e', '#6e3320'] },
  { sky: ['#d9eef7', '#9cc9e2', '#5c9ec4'], sun: '#ffffff', layers: ['#4b7fa3', '#2f5d7c', '#1d3f57'] },
  { sky: ['#e3f6e6', '#9fd8ac', '#52b788'], sun: '#fffbe8', layers: ['#2d8a5f', '#1b6b47', '#12462f'] },
] as const;

function hash(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function prng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Scene = 'waves' | 'mountains' | 'skyline' | 'hills';

const SCENES: Scene[] = ['waves', 'mountains', 'skyline', 'hills'];

/** Picks a scene from tag hints (e.g. post tags); falls back to a seed-derived scene. */
function sceneFor(hints: readonly string[], seed: number): Scene {
  for (const hint of hints) {
    if (['beaches', 'beach', 'surf'].includes(hint)) return 'waves';
    if (['nature', 'adventure', 'hiking', 'trail', 'park'].includes(hint)) return 'mountains';
    if (['culture', 'architecture', 'history', 'food', 'nightlife', 'shopping', 'museum'].includes(hint)) return 'skyline';
  }
  return SCENES[seed % SCENES.length] ?? 'hills';
}

function layerPath(scene: Scene, rand: () => number, baseY: number, amplitude: number): string {
  const W = 400;
  const H = 300;
  switch (scene) {
    case 'waves': {
      let d = `M0 ${baseY}`;
      const segments = 4 + Math.floor(rand() * 3);
      const step = W / segments;
      for (let i = 0; i < segments; i++) {
        const x = (i + 1) * step;
        const cy = baseY + (i % 2 === 0 ? -amplitude : amplitude) * (0.6 + rand() * 0.4);
        d += ` Q${x - step / 2} ${cy} ${x} ${baseY}`;
      }
      return `${d} L${W} ${H} L0 ${H} Z`;
    }
    case 'mountains': {
      let d = `M0 ${baseY}`;
      let x = 0;
      while (x < W) {
        const w = 50 + rand() * 90;
        const peak = baseY - amplitude * (0.5 + rand() * 0.9);
        d += ` L${x + w / 2} ${peak} L${Math.min(W, x + w)} ${baseY - rand() * amplitude * 0.3}`;
        x += w;
      }
      return `${d} L${W} ${H} L0 ${H} Z`;
    }
    case 'skyline': {
      let d = `M0 ${H} L0 ${baseY}`;
      let x = 0;
      while (x < W) {
        const w = 14 + rand() * 34;
        const top = baseY - amplitude * rand() * 1.4;
        d += ` L${x} ${top} L${Math.min(W, x + w)} ${top}`;
        if (rand() > 0.82) {
          const mid = x + w / 2;
          d += ` L${mid} ${top - 18 - rand() * 22} L${Math.min(W, x + w)} ${top}`;
        }
        x += w;
      }
      return `${d} L${W} ${baseY} L${W} ${H} Z`;
    }
    case 'hills': {
      const c1 = baseY - amplitude * (0.4 + rand());
      const c2 = baseY - amplitude * (0.2 + rand());
      return `M0 ${baseY} C${W * 0.3} ${c1} ${W * 0.6} ${c2} ${W} ${baseY - rand() * amplitude} L${W} ${H} L0 ${H} Z`;
    }
  }
}

export function DestinationArt({
  seed,
  categories = [],
  className,
}: {
  seed: string;
  categories?: readonly string[];
  className?: string;
}) {
  const h = hash(seed);
  const palette = PALETTES[h % PALETTES.length] ?? PALETTES[0];
  const rand = prng(h);
  const scene = sceneFor(categories, h);
  const gid = `sky-${h.toString(36)}`;
  const sunX = 70 + rand() * 260;
  const sunY = 70 + rand() * 50;
  const layers = [
    { y: 190, a: 46, fill: palette.layers[0], opacity: 0.55 },
    { y: 220, a: 38, fill: palette.layers[1], opacity: 0.8 },
    { y: 252, a: 26, fill: palette.layers[2], opacity: 1 },
  ];

  return (
    <svg
      viewBox="0 0 400 300"
      preserveAspectRatio="xMidYMid slice"
      className={cn('block size-full', className)}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={palette.sky[0]} />
          <stop offset="0.55" stopColor={palette.sky[1]} />
          <stop offset="1" stopColor={palette.sky[2]} />
        </linearGradient>
      </defs>
      <rect width="400" height="300" fill={`url(#${gid})`} />
      <circle cx={sunX} cy={sunY} r={28 + rand() * 18} fill={palette.sun} opacity="0.9" />
      {layers.map((l, i) => (
        <path key={i} d={layerPath(scene, rand, l.y, l.a)} fill={l.fill} opacity={l.opacity} />
      ))}
    </svg>
  );
}
