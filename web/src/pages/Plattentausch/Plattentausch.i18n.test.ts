/** Keine unübersetzten deutschen Texte oder fest verdrahteten Farben in der Seite Plattentausch. */
import { describe, expect, it } from 'vitest';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';

const sources = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('Plattentausch i18n', () => {
  it('keine unübersetzten deutschen Texte', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });
});
