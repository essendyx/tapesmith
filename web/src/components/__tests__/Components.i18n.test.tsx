/** Keine deutschen Literale und keine festen Farben in Hülle, Befehlen, Routen und den gemeinsamen Komponenten. */
import { describe, expect, it } from 'vitest';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';

const shell = import.meta.glob('../../shell/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const commands = import.meta.glob('../../commands/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const routes = import.meta.glob('../../routes.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const app = import.meta.glob('../../App.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const components = import.meta.glob(
  [
    '../ConfirmProvider.tsx',
    '../NotifyProvider.tsx',
    '../PlausiHint.tsx',
    '../PrintOptionsBar.tsx',
    '../TapePreview.tsx',
    '../WarningList.tsx',
    '../useMediaQuery.ts',
    '../usePrint.ts',
  ],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>;

const all = { ...shell, ...commands, ...routes, ...app, ...components };

describe('Übersetzung der Hülle und Komponenten', () => {
  it('findet alle Quellen', () => {
    expect(Object.keys(shell).length).toBeGreaterThan(10);
    expect(Object.keys(commands).length).toBeGreaterThan(5);
    expect(Object.keys(components)).toHaveLength(8);
    expect(Object.keys(routes)).toHaveLength(1);
  });

  it('keine deutschen Literale', () => {
    expect(findGermanLiterals(all)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(all)).toEqual([]);
  });
});
