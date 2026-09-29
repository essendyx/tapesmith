/** i18n-Prüfung der Seite Homelab: kein unübersetzter deutscher Text, keine harte Farbe. */
import { describe, expect, it } from 'vitest';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';

const sources = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('Seite Homelab: i18n', () => {
  it('kein unübersetzter deutscher Text', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahtete Farbe', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });
});
