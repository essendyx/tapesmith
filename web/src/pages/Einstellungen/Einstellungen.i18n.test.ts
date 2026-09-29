import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';
import { mockApi, renderWithProviders } from '../../test/utils';
import { i18n } from '../../i18n';
import { baseSettingsRoutes, ALL_SETTINGS_SECTIONS } from './testFixtures';
import EinstellungenPage from './index';

const tsx = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const ts = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
// `testFixtures.ts` ist reine Testinfrastruktur (Mock-Daten für Vitest, kein Laufzeitcode und keine
// Nutzeroberfläche); `findGermanLiterals` erkennt nur `*.test.ts(x)` als Testdatei, deshalb hier von Hand ausgenommen.
const sources = Object.fromEntries(
  Object.entries({ ...tsx, ...ts }).filter(([file]) => !file.endsWith('/testFixtures.ts')),
);

describe('Einstellungen: Übersetzung', () => {
  it('keine deutschen Literale in pages/Einstellungen (außer Tests)', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });

  it('de/einstellungen.json und en/einstellungen.json enthalten für jeden Abschnitt und jedes Feld des echten Schemas einen Eintrag', () => {
    for (const lang of ['de', 'en'] as const) {
      for (const section of ALL_SETTINGS_SECTIONS) {
        expect(i18n.exists(`einstellungen:sections.${section.id}`, { lng: lang })).toBe(true);
        for (const field of section.fields) {
          expect(i18n.exists(`einstellungen:fields.${field}.label`, { lng: lang })).toBe(true);
        }
      }
    }
  });

  it('Englisch: Überschrift und Hauptaktion (Suchfeld)', async () => {
    mockApi(baseSettingsRoutes());
    renderWithProviders(createElement(EinstellungenPage), { route: '/einstellungen', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Search settings' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Updates' })).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'Help and diagnostics' })).toBeInTheDocument();
  });
});
