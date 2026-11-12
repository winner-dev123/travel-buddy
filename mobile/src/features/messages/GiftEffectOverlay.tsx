import { memo, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  StyleSheet,
  useWindowDimensions,
  View,
  type ImageSourcePropType,
} from 'react-native';

import type { GiftEffect } from './gifts';

const PETALS: ImageSourcePropType[] = [
  require('../../../assets/gifts/effects/petal_blush.png') as number,
  require('../../../assets/gifts/effects/petal_pink.png') as number,
  require('../../../assets/gifts/effects/petal_rose.png') as number,
];
const DROPS: ImageSourcePropType[] = [
  require('../../../assets/gifts/effects/drop_blue.png') as number,
  require('../../../assets/gifts/effects/drop_light.png') as number,
];
const HEARTS: ImageSourcePropType[] = [
  require('../../../assets/gifts/effects/heart_red.png') as number,
  require('../../../assets/gifts/effects/heart_pink.png') as number,
];
const CONFETTI = ['#F5C451', '#FF6B6B', '#2EC4B6', '#9B5DE5', '#4CC9F0', '#F15BB5', '#FFFFFF'];
const RIPPLE = 'rgba(140, 210, 255, 0.9)';

/** How long each effect plays, in ms. */
export const GIFT_EFFECT_DURATION: Record<GiftEffect, number> = {
  petals: 4200,
  splash: 2800,
  confetti: 3600,
  hearts: 3600,
};

// Keyframes per particle: one shared clock drives every particle through its own sampled path.
const STEPS = 18;

interface Frame {
  x: number;
  y: number;
  rotate?: number;
  scaleX?: number;
  scaleY?: number;
  opacity: number;
}

interface Particle {
  key: string;
  width: number;
  height: number;
  source?: ImageSourcePropType;
  /** A confetti piece's colour. */
  color?: string;
  /** A ripple ring's colour. */
  ring?: string;
  radius?: number;
  start: number;
  end: number;
  at: (u: number) => Frame;
}

type Random = () => number;
type Builder = (width: number, height: number, random: Random) => Particle[];

/** 0→1 over the first `fadeIn` of a path, 1 in between, 1→0 after `fadeOut`. */
function fade(u: number, fadeIn: number, fadeOut: number): number {
  if (u < fadeIn) return u / fadeIn;
  if (u > fadeOut) return Math.max(0, (1 - u) / (1 - fadeOut));
  return 1;
}

const sign = (random: Random) => (random() < 0.5 ? -1 : 1);

// Flower petals drift down from the top, swaying and turning over as they fall: a full shower.
const petals: Builder = (width, height, random) =>
  Array.from({ length: 44 }, (_, i) => {
    const size = 18 + random() * 16;
    const x0 = random() * width;
    const drift = (random() - 0.5) * 120;
    const sway = 16 + random() * 26;
    const waves = 1 + random() * 1.4;
    const phase = random() * Math.PI * 2;
    const spin = sign(random) * (160 + random() * 320);
    const turn = random() * 360;
    const flutter = 2 + random() * 2.5;
    const alpha = 0.8 + random() * 0.2;
    const start = random() * 0.42;
    return {
      key: `petal-${i}`,
      width: size,
      height: size,
      source: PETALS[i % PETALS.length],
      start,
      end: Math.min(1, start + 0.5 + random() * 0.12),
      at: (u) => ({
        x: x0 + drift * u + sway * Math.sin(2 * Math.PI * waves * u + phase),
        y: -size + u * (height + size * 2),
        rotate: turn + spin * u,
        scaleX: 0.35 + 0.65 * Math.abs(Math.cos(Math.PI * flutter * u + phase)),
        opacity: alpha * fade(u, 0.06, 0.85),
      }),
    };
  });

// Water bursts up from the bottom and falls back, ripples spread where it hit, and a few drops
// land on the screen and run down it.
const splash: Builder = (width, height, random) => {
  const ox = width / 2;
  const oy = height * 0.9;
  const drops: Particle[] = Array.from({ length: 36 }, (_, i) => {
    const size = 9 + random() * 15;
    const jitter = (random() - 0.5) * 40;
    const reach = (random() - 0.5) * width * 1.3;
    const rise = height * (0.35 + random() * 0.45);
    const peak = 0.38 + random() * 0.12;
    const start = random() * 0.12;
    return {
      key: `drop-${i}`,
      width: size,
      height: size,
      source: DROPS[i % DROPS.length],
      start,
      end: Math.min(1, start + 0.62 + random() * 0.3),
      at: (u) => {
        // Rises to `rise` at `peak`, then falls past where it started; the drop points along
        // its path and stretches with its speed.
        const fall = 1 - u / peak;
        const dy = (-2 * rise * fall) / peak;
        return {
          x: ox + jitter + reach * u,
          y: oy - rise * ((2 * u) / peak - (u / peak) ** 2),
          rotate: (Math.atan2(-reach, dy) * 180) / Math.PI,
          scaleY: 1 + Math.min(0.35, 0.3 * Math.abs(fall)),
          opacity: fade(u, 0.03, 0.8),
        };
      },
    };
  });
  const onGlass: Particle[] = Array.from({ length: 9 }, (_, i) => {
    const size = 26 + random() * 18;
    const x = width * (0.1 + random() * 0.8);
    const y = height * (0.12 + random() * 0.55);
    const slide = 30 + random() * 60;
    const start = 0.18 + random() * 0.25;
    return {
      key: `glass-${i}`,
      width: size,
      height: size,
      source: DROPS[1],
      start,
      end: Math.min(1, start + 0.5 + random() * 0.2),
      at: (u) => {
        const pop = u < 0.12 ? 0.2 + (u / 0.12) * 0.9 : 1.1 - 0.1 * Math.min(1, (u - 0.12) / 0.1);
        return {
          x,
          y: y + slide * u * u,
          scaleX: pop,
          scaleY: pop * (1 + 0.15 * u),
          opacity: 0.9 * fade(u, 0.05, 0.6),
        };
      },
    };
  });
  const ripples: Particle[] = [0, 1, 2].map((i) => ({
    key: `ripple-${i}`,
    width: 80,
    height: 80,
    ring: RIPPLE,
    radius: 40,
    start: i * 0.1,
    end: i * 0.1 + 0.55,
    at: (u) => {
      const grow = 0.2 + 3 * (1 - (1 - u) ** 2);
      return { x: ox, y: oy, scaleX: grow, scaleY: grow * 0.32, opacity: 0.9 * (1 - u) };
    },
  }));
  return [...ripples, ...drops, ...onGlass];
};

// Confetti shoots up from both bottom corners, then tumbles down.
const confetti: Builder = (width, height, random) =>
  Array.from({ length: 48 }, (_, i) => {
    const left = i % 2 === 0;
    const ox = left ? -10 : width + 10;
    const oy = height * 0.98;
    const dot = random() < 0.2;
    const w = dot ? 8 + random() * 2 : 7 + random() * 5;
    const h = dot ? w : w * (1.4 + random() * 0.8);
    const reach = width * (0.35 + random() * 0.6) * (left ? 1 : -1);
    const rise = height * (0.55 + random() * 0.35);
    const drop = height * (0.45 + random() * 0.4);
    const sway = 10 + random() * 20;
    const waves = 1 + random() * 2;
    const phase = random() * Math.PI * 2;
    const spin = sign(random) * (360 + random() * 540);
    const turn = random() * 360;
    const flips = 2 + random() * 3;
    const start = random() * 0.1;
    const drag = 1 - Math.exp(-5);
    return {
      key: `confetti-${i}`,
      width: w,
      height: h,
      color: CONFETTI[i % CONFETTI.length],
      radius: dot ? w / 2 : 2,
      start,
      end: Math.min(1, start + 0.78 + random() * 0.2),
      at: (u) => {
        // Fast out of the corner, slowed by the air, then falling.
        const out = (1 - Math.exp(-5 * u)) / drag;
        return {
          x: ox + reach * out + sway * u * Math.sin(2 * Math.PI * waves * u + phase),
          y: oy - rise * out + drop * u * u,
          rotate: turn + spin * u,
          scaleY: 0.25 + 0.75 * Math.abs(Math.cos(2 * Math.PI * flips * u + phase)),
          opacity: fade(u, 0.02, 0.82),
        };
      },
    };
  });

// Hearts float up from the bottom, popping in and fading as they rise.
const hearts: Builder = (width, height, random) =>
  Array.from({ length: 20 }, (_, i) => {
    const size = 22 + random() * 22;
    const x0 = width * (0.08 + random() * 0.84);
    const top = height * (0.08 + random() * 0.3);
    const sway = 12 + random() * 20;
    const waves = 0.8 + random() * 0.8;
    const phase = random() * Math.PI * 2;
    const start = random() * 0.45;
    return {
      key: `heart-${i}`,
      width: size,
      height: size,
      source: HEARTS[i % HEARTS.length],
      start,
      end: Math.min(1, start + 0.45 + random() * 0.12),
      at: (u) => {
        const pop =
          u < 0.15 ? 0.4 + (u / 0.15) * 0.75 : 1.15 - 0.15 * Math.min(1, (u - 0.15) / 0.15);
        return {
          x: x0 + sway * Math.sin(2 * Math.PI * waves * u + phase),
          y: height + size - (height + size - top) * (1 - (1 - u) ** 2),
          rotate: 12 * Math.sin(2 * Math.PI * waves * u + phase + 1),
          scaleX: pop,
          scaleY: pop,
          opacity: fade(u, 0.08, 0.7),
        };
      },
    };
  });

const BUILDERS: Record<GiftEffect, Builder> = { petals, splash, confetti, hearts };

/** Samples a particle's path into keyframes on the shared clock. */
function animatedStyle(progress: Animated.Value, p: Particle) {
  const input: number[] = [];
  const frames: Frame[] = [];
  for (let i = 0; i <= STEPS; i++) {
    const u = i / STEPS;
    input.push(p.start + (p.end - p.start) * u);
    frames.push(p.at(u));
  }
  const track = (pick: (f: Frame) => number) =>
    progress.interpolate({
      inputRange: input,
      outputRange: frames.map(pick),
      extrapolate: 'clamp',
    });
  return {
    width: p.width,
    height: p.height,
    marginLeft: -p.width / 2,
    marginTop: -p.height / 2,
    ...(p.color ? { backgroundColor: p.color } : {}),
    ...(p.radius ? { borderRadius: p.radius } : {}),
    ...(p.ring ? { borderWidth: 3, borderColor: p.ring } : {}),
    opacity: track((f) => f.opacity),
    transform: [
      { translateX: track((f) => f.x) },
      { translateY: track((f) => f.y) },
      {
        rotate: progress.interpolate({
          inputRange: input,
          outputRange: frames.map((f) => `${f.rotate ?? 0}deg`),
          extrapolate: 'clamp',
        }),
      },
      { scaleX: track((f) => f.scaleX ?? 1) },
      { scaleY: track((f) => f.scaleY ?? 1) },
    ],
  };
}

export interface GiftEffectOverlayProps {
  effect: GiftEffect;
  /** Called once the effect has finished playing. */
  onDone: () => void;
}

/**
 * The effect that plays over the whole chat when a gift is opened (DM-016): flower petals, a
 * water splash, confetti or hearts, as the sender chose. It never takes touches, is hidden from
 * screen readers, and is drawn with the native driver from one clock. Mount it with a new `key`
 * to play it again.
 */
export const GiftEffectOverlay = memo(function GiftEffectOverlay({
  effect,
  onDone,
}: GiftEffectOverlayProps) {
  const { width, height } = useWindowDimensions();
  const [scene] = useState(() => {
    const progress = new Animated.Value(0);
    const layers = BUILDERS[effect](width, height, Math.random).map((particle) => ({
      particle,
      style: animatedStyle(progress, particle),
    }));
    return { progress, layers };
  });
  const finish = useRef(onDone);
  useEffect(() => {
    finish.current = onDone;
  }, [onDone]);

  useEffect(() => {
    const duration = GIFT_EFFECT_DURATION[effect];
    const run = Animated.timing(scene.progress, {
      toValue: 1,
      duration,
      easing: Easing.linear,
      useNativeDriver: true,
    });
    run.start();
    const done = setTimeout(() => finish.current(), duration + 50);
    return () => {
      run.stop();
      clearTimeout(done);
    };
  }, [effect, scene]);

  return (
    <View
      pointerEvents="none"
      style={styles.overlay}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      testID={`gift-effect-${effect}`}
    >
      {scene.layers.map(({ particle, style }) =>
        particle.source ? (
          <Animated.Image
            key={particle.key}
            source={particle.source}
            style={[styles.particle, style]}
            resizeMode="contain"
          />
        ) : (
          <Animated.View key={particle.key} style={[styles.particle, style]} />
        ),
      )}
    </View>
  );
});

const styles = StyleSheet.create({
  overlay: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 20,
    elevation: 20,
  },
  particle: { position: 'absolute', left: 0, top: 0 },
});
