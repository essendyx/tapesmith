/**
 * Globaler Übersetzungs-Wächter: keine deutschen Literale und keine fest verdrahteten
 * Farben in irgendeiner `.tsx`- oder `.ts`-Datei der Oberfläche (auch API-Clients, Plattform- und
 * Hilfsmodule, die Fehlertexte bauen). Ausgenommen sind Tests und Testdaten (`testFixtures.ts`; erkennt
 * `findGermanLiterals` selbst), die Test-Hilfen unter `src/test/**` und das Theme unter
 * `src/theme/**` (dort sind Farbwerte und Kontrastpaletten gewollt). Fachlich richtige Ausnahmen
 * (Server-Werte, Bandfarben aus Daten) tragen im Quelltext `// i18n-ignore` mit Begründung.
 */
import { describe, expect, it } from 'vitest';
import { findGermanLiterals, findHardcodedColors } from '../test/untranslated';

const sources = import.meta.glob(['../**/*.tsx', '../**/*.ts', '!../test/**', '!../theme/**', '!../**/*.d.ts', '!../**/testFixtures.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

describe('Übersetzungs-Wächter über alle Seiten und Bausteine', () => {
  it('findet die Quelltexte (Seiten, Hülle, Bausteine)', () => {
    const files = Object.keys(sources);
    expect(files.length).toBeGreaterThan(100);
    expect(files.some((f) => f.includes('/pages/Editor/'))).toBe(true);
    expect(files.some((f) => f.includes('/shell/'))).toBe(true);
    expect(files.some((f) => f.includes('/components/'))).toBe(true);
    expect(files.some((f) => f.includes('/theme/') || f.includes('/test/'))).toBe(false);
    expect(files.some((f) => f.endsWith('/platform.ts'))).toBe(true);
    expect(files.some((f) => f.endsWith('/api/client.ts'))).toBe(true);
  });

  it('keine deutschen Literale außerhalb der Übersetzungsdateien', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben außerhalb des Themes', () => {
    // Gekennzeichnete Ausnahmen (z. B. Rückfall auf die weiße Bandfarbe aus Daten) zählen nicht.
    expect(findHardcodedColors(sources, [/i18n-ignore/])).toEqual([]);
  });
});
