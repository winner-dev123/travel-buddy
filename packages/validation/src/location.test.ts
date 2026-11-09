import { describe, expect, it } from 'vitest';
import { distanceKm, parseNearParam, roundCoordinate, toNearParam } from './location';
import { ageOn, createPostSchema, feedTabFromSlug, registerSchema } from './schemas';

describe('location privacy helpers', () => {
  it('rounds to 3 decimals (~110 m)', () => {
    expect(roundCoordinate(-22.906847)).toBe(-22.907);
    expect(roundCoordinate(-43.172896)).toBe(-43.173);
  });

  it('normalizes negative zero', () => {
    expect(Object.is(roundCoordinate(-0.0001), 0)).toBe(true);
  });

  it('never emits more than 3 decimals in the near param', () => {
    expect(toNearParam(51.507351, -0.127758)).toBe('51.507,-0.128');
  });

  it('rejects out-of-range coordinates', () => {
    expect(toNearParam(91, 0)).toBeNull();
    expect(toNearParam(0, 181)).toBeNull();
    expect(toNearParam(Number.NaN, 0)).toBeNull();
  });

  it('parses and re-rounds near values, rejecting junk', () => {
    expect(parseNearParam('-22.9068471,-43.1728965')).toEqual({ lat: -22.907, lng: -43.173 });
    expect(parseNearParam('abc')).toBeNull();
    expect(parseNearParam('100,0')).toBeNull();
    expect(parseNearParam(undefined)).toBeNull();
  });

  it('computes plausible great-circle distances', () => {
    const rio = { lat: -22.9068, lng: -43.1729 };
    const saoPaulo = { lat: -23.5505, lng: -46.6333 };
    expect(distanceKm(rio, saoPaulo)).toBeGreaterThan(340);
    expect(distanceKm(rio, saoPaulo)).toBeLessThan(370);
  });
});

describe('schemas', () => {
  it('enforces the 18+ gate and terms acceptance on registration', () => {
    const base = { display_name: 'Amelia', email: 'amelia@example.com', terms_accepted: true };
    expect(registerSchema.safeParse({ ...base, birth_date: '1990-04-12' }).success).toBe(true);
    const minor = registerSchema.safeParse({ ...base, birth_date: '2015-01-01' });
    expect(minor.success).toBe(false);
    if (!minor.success) expect(minor.error.issues[0]?.message).toBe('validation.underage');
    expect(registerSchema.safeParse({ ...base, birth_date: '1990-02-30' }).success).toBe(false);
    expect(
      registerSchema.safeParse({ ...base, birth_date: '1990-04-12', terms_accepted: false }).success,
    ).toBe(false);
  });

  it('computes age across the birthday boundary', () => {
    const today = new Date(Date.UTC(2026, 10, 9));
    expect(ageOn('2008-11-09', today)).toBe(18);
    expect(ageOn('2008-11-10', today)).toBe(17);
  });

  it('accepts a minimal valid post (contract CreatePostRequest)', () => {
    const result = createPostSchema.safeParse({
      kind: 'text',
      body: 'Sunrise at the beach',
      visibility: 'public',
      location_precision: 'none',
    });
    expect(result.success).toBe(true);
  });

  it('rejects empty bodies, too many tags and a location precision without a destination', () => {
    const result = createPostSchema.safeParse({
      kind: 'text',
      body: '   ',
      visibility: 'public',
      location_precision: 'destination',
      tags: Array.from({ length: 11 }, (_, i) => `tag${i}`),
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths).toContain('body');
      expect(paths).toContain('tags');
    }
    const noDestination = createPostSchema.safeParse({ kind: 'text', body: 'x', visibility: 'public', location_precision: 'destination' });
    expect(noDestination.success).toBe(false);
  });

  it('maps URL feed slugs to API tabs with a safe default', () => {
    expect(feedTabFromSlug('for-you')).toBe('for_you');
    expect(feedTabFromSlug('nearby')).toBe('nearby');
    expect(feedTabFromSlug('../admin')).toBe('for_you');
    expect(feedTabFromSlug(null)).toBe('for_you');
  });
});
