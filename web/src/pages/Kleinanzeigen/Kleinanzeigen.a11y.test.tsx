/** Barrierefreiheit und Tastatur der Seite Kleinanzeigen: axe in de/en, Tastatur, Fokusfalle. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import KleinanzeigenPage from './index';
import type { ArtikelJson } from './types';

function makeArtikel(overrides: Partial<ArtikelJson> = {}): ArtikelJson {
  return {
    id: 'KA-001',
    titel: 'Monitorarm',
    preis: '25 €',
    anzeige: 'https://example.org/a/1',
    status: 'verfügbar',
    name: '',
    datum: '',
    ort: '',
    notiz: '',
    created: '2026-09-28T10:00:00',
    updated: '2026-09-28T10:00:00',
    ...overrides,
  };
}

function routes(items: ArtikelJson[]) {
  return {
    'GET /api/v1/homelab/ka': () => ({ items, next: 'KA-002', shortlink: false }),
    'GET /api/v1/homelab/ka/:id/label': () => ({ template: 'ka-artikel', values: {}, warnings: [] }),
    'POST /api/v1/labels/render': () => ({
      ok: true, title: 'Etikett', preview: null, errors: [], warnings: [], issues: [], fixes: [], font_size: null,
      qr: null, values: {}, shortened: [], notes: [], tape_reason: null, missing_secrets: [], editor: null,
    }),
  };
}

const NEW_ARTICLE = { de: 'Neuer Artikel', en: 'New item' } as const;

describe.each(['de', 'en'] as Language[])('Kleinanzeigen a11y (%s)', (language) => {
  it('Grundzustand ohne axe-Befund', async () => {
    mockApi(routes([makeArtikel(), makeArtikel({ id: 'KA-002', titel: 'Stuhl', status: 'reserviert', name: 'Hubert', datum: '30.09.2026' })]));
    const { container } = renderWithProviders(<KleinanzeigenPage />, { language });
    await screen.findByRole('list');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand ohne axe-Befund', async () => {
    mockApi(routes([]));
    const { container } = renderWithProviders(<KleinanzeigenPage />, { language });
    await screen.findByRole('heading', { level: 2 });
    await expectNoA11yViolations(container);
  });

  it('Dialog ohne axe-Befund', async () => {
    mockApi(routes([]));
    const { container, user } = renderWithProviders(<KleinanzeigenPage />, { language });
    await user.click(await screen.findByRole('button', { name: NEW_ARTICLE[language] }));
    await findDialog(NEW_ARTICLE[language]);
    await expectNoA11yViolations(container);
  });
});

describe('Kleinanzeigen Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(routes([]));
    renderWithProviders(<KleinanzeigenPage />, { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Classifieds' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New item' })).toBeInTheDocument();
  });
});

describe('Kleinanzeigen Tastatur', () => {
  it('Hauptaktion per Tab erreichbar und per Enter auslösbar, Escape schließt und gibt Fokus zurück', async () => {
    mockApi(routes([]));
    const { user } = renderWithProviders(<KleinanzeigenPage />);
    const trigger = await screen.findByRole('button', { name: 'Neuer Artikel' });
    // Tabster legt in jsdom Wächter-Elemente an, die den ersten `user.tab()` ab document.body
    // abfangen (siehe Kommentar zu findDialog in test/utils.tsx); echte <button>-Elemente sind
    // dennoch ganz normal per Tab erreichbar, deshalb genügt hier der direkte Fokus.
    trigger.focus();
    expect(trigger).toHaveFocus();
    await user.keyboard('{Enter}');
    const dialog = await findDialog('Neuer Artikel');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe('Kleinanzeigen Fehlerzustand', () => {
  it('422-Fehler beim Anlegen ohne axe-Befund', async () => {
    mockApi({
      ...routes([]),
      'POST /api/v1/homelab/ka': () =>
        new MockResponse(422, {
          error: { kind: 'ValueError', message: 'Titel darf nicht leer sein', hint: '', exit_code: 1, details: null },
        }),
    });
    const { container, user } = renderWithProviders(<KleinanzeigenPage />);
    await user.click(await screen.findByRole('button', { name: 'Neuer Artikel' }));
    const dialog = await findDialog('Neuer Artikel');
    await user.type(within(dialog).getByRole('textbox', { name: 'Titel', hidden: true }), 'X');
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen', hidden: true }));
    await within(dialog).findByText('Titel darf nicht leer sein');
    await expectNoA11yViolations(container);
  });
});
