/** Sucht unübersetzte deutsche Texte und fest verdrahtete Farben in der Galerie. */
import { describe, expect, it } from 'vitest';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';

const sources = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('Galerie: i18n', () => {
  it('keine unübersetzten deutschen Texte', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });
});
