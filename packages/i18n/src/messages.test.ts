import { describe, expect, it } from 'vitest';
import de from '../messages/de.json';
import en from '../messages/en.json';
import es from '../messages/es.json';
import fr from '../messages/fr.json';
import ptBR from '../messages/pt-BR.json';
import { LOCALES, SUPPORTED_LOCALES } from './index';

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    if (typeof value === 'string') out[prefix + key] = value;
    else Object.assign(out, flatten(value, `${prefix}${key}.`));
  }
  return out;
}

/** ICU argument names: `{name}` or `{count, plural, ...}` — not literal text inside plural branches. */
function argumentsOf(message: string): string[] {
  return [...message.matchAll(/\{\s*([A-Za-z_]\w*)\s*[,}]/g)].map((m) => m[1] as string).sort();
}

function tagsOf(message: string): string[] {
  return [...message.matchAll(/<\/?([a-z]+)>/g)].map((m) => m[0]).sort();
}

const source = flatten(en as Tree);
const catalogs: Record<string, Record<string, string>> = {
  es: flatten(es as Tree),
  'pt-BR': flatten(ptBR as Tree),
  fr: flatten(fr as Tree),
  de: flatten(de as Tree),
};

describe('message catalogs', () => {
  it('has a catalog for every registered locale', () => {
    expect(LOCALES.map((l) => l.code)).toEqual([...SUPPORTED_LOCALES]);
    for (const code of SUPPORTED_LOCALES.filter((c) => c !== 'en')) expect(catalogs[code]).toBeDefined();
  });

  for (const [locale, catalog] of Object.entries(catalogs)) {
    describe(locale, () => {
      it('has exactly the same keys as English', () => {
        expect(Object.keys(catalog).sort()).toEqual(Object.keys(source).sort());
      });

      it('keeps every ICU argument and rich-text tag', () => {
        const problems = Object.keys(source).filter(
          (key) =>
            catalog[key] !== undefined &&
            (argumentsOf(catalog[key] as string).join() !== argumentsOf(source[key] as string).join() ||
              tagsOf(catalog[key] as string).join() !== tagsOf(source[key] as string).join()),
        );
        expect(problems).toEqual([]);
      });

      it('has no empty strings', () => {
        expect(Object.entries(catalog).filter(([, v]) => v.trim() === '').map(([k]) => k)).toEqual([]);
      });
    });
  }
});
