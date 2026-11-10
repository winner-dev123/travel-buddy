// req: NFR-014
/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'fs';
import { join, relative } from 'path';

/**
 * Every user-facing string comes from the translation resources: no literal words in JSX text
 * or in the props that render text. Emoji, punctuation and interpolations are fine.
 */
const ROOT = join(__dirname, '..', '..', '..');
const JSX_TEXT = />\s*([^<>{}=;()]*[A-Za-z]{3,}[^<>{}=;()]*?)\s*<\/[A-Z]/gs;
const TEXT_PROP =
  /\b(label|title|placeholder|accessibilityLabel|accessibilityHint|hint)="([^"]*[A-Za-z]{3,}[^"]*)"/g;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      return name === '__tests__' || name === 'node_modules' ? [] : sources(path);
    }
    return path.endsWith('.tsx') ? [path] : [];
  });
}

describe('externalized UI strings', () => {
  const files = [...sources(join(ROOT, 'app')), ...sources(join(ROOT, 'src'))];

  it('scans the screens and components', () => {
    expect(files.length).toBeGreaterThan(40);
  });

  it('has no literal words in JSX text or text props', () => {
    const found = files.flatMap((file) => {
      const text = readFileSync(file, 'utf8');
      const where = relative(ROOT, file);
      return [
        ...[...text.matchAll(JSX_TEXT)].map((m) => `${where}: ${m[1]?.trim()}`),
        ...[...text.matchAll(TEXT_PROP)].map((m) => `${where}: ${m[0]}`),
      ];
    });
    expect(found).toEqual([]);
  });
});
