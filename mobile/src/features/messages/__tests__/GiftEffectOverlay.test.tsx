// req: DM-016
import { act, render, screen } from '@testing-library/react-native';

import { GIFT_EFFECT_DURATION, GiftEffectOverlay } from '../GiftEffectOverlay';
import { GIFT_EFFECTS, giftEffectOf, isGiftEffect } from '../gifts';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

// The overlay is hidden from screen readers, so it is found among hidden elements.
const overlay = (effect: string) =>
  screen.queryByTestId(`gift-effect-${effect}`, { includeHiddenElements: true });

describe('gift effects', () => {
  it.each(GIFT_EFFECTS)(
    'plays %s without taking touches or screen reader focus',
    async (effect) => {
      const onDone = jest.fn();
      await render(<GiftEffectOverlay effect={effect} onDone={onDone} />);
      const root = overlay(effect)!;
      expect(root).toBeTruthy();
      expect(root).toHaveProp('pointerEvents', 'none');
      expect(root).toHaveProp('importantForAccessibility', 'no-hide-descendants');
      expect(root.children.length).toBeGreaterThan(10); // a shower, not a single sprite

      await act(async () => {
        jest.advanceTimersByTime(GIFT_EFFECT_DURATION[effect] - 100);
      });
      expect(onDone).not.toHaveBeenCalled();
      await act(async () => {
        jest.advanceTimersByTime(200);
      });
      expect(onDone).toHaveBeenCalledTimes(1);
    },
  );

  it('keeps playing when the chat re-renders it with a new callback', async () => {
    const first = jest.fn();
    const second = jest.fn();
    const view = await render(<GiftEffectOverlay effect="petals" onDone={first} />);
    await act(async () => {
      jest.advanceTimersByTime(GIFT_EFFECT_DURATION.petals / 2);
    });
    await view.rerender(<GiftEffectOverlay effect="petals" onDone={second} />);
    await act(async () => {
      jest.advanceTimersByTime(GIFT_EFFECT_DURATION.petals / 2 + 100);
    });
    // The clock didn't restart, and the latest callback is the one told.
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('stops quietly when it is removed early', async () => {
    const onDone = jest.fn();
    const view = await render(<GiftEffectOverlay effect="splash" onDone={onDone} />);
    await view.unmount();
    await act(async () => {
      jest.advanceTimersByTime(GIFT_EFFECT_DURATION.splash * 2);
    });
    expect(onDone).not.toHaveBeenCalled();
  });

  it('plays petals for an effect this app does not know', () => {
    expect(GIFT_EFFECTS).toEqual(['petals', 'splash', 'confetti', 'hearts']);
    expect(isGiftEffect('hearts')).toBe(true);
    expect(isGiftEffect('fireworks')).toBe(false);
    expect(giftEffectOf('confetti')).toBe('confetti');
    expect(giftEffectOf('fireworks')).toBe('petals');
    expect(giftEffectOf(undefined)).toBe('petals'); // a gift from before effects
  });
});
