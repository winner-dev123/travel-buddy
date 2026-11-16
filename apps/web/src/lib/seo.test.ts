import { describe, expect, it } from 'vitest';
import { destinationRobots } from './seo';

describe('destinationRobots (ADR-0035)', () => {
  it('indexes directory destinations and keeps gazetteer towns out of search results, links still followed', () => {
    expect(destinationRobots({ listed: true })).toEqual({});
    expect(destinationRobots({ listed: false })).toEqual({ robots: { index: false, follow: true } });
  });
});
