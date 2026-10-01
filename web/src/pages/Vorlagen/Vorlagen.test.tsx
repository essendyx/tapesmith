import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { chooseRowAction, findDialogByRole, fixtures, mockApi, MockResponse, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { FieldJson, TemplateDetail, TemplateSummary } from '../../api/types';
import VorlagenPage from './index';

afterEach(() => {
  restoreAllMocks();
});

/** Simuliert matchMedia für die Breite-Erkennung (gleiches Muster wie theme/ThemeProvider.test.tsx). Nur die
 *  Breite-Abfrage matchen, sonst würde die pauschale Antwort auch die (davon unabhängige) Dunkelmodus-Abfrage
 *  des ThemeProviders auf „true“ setzen und das Theme ungewollt umschalten. */
function mockNarrowScreen(matches: boolean) {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: matches && query.includes('max-width'),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}

function field(o: Partial<FieldJson> = {}): FieldJson {
  return { id: 'sn', label: 'Seriennummer', type: 'input', default: '', required: true, secret: false, choices: [], max_len: null, multiline: false, ...o };
}

function summary(o: Partial<TemplateSummary> = {}): TemplateSummary {
  return {
    name: 'datentraeger',
    description: 'SSD- und HDD-Etiketten',
    category: 'Datenträger',
    tags: [],
    kind: 'layout',
    builtin: true,
    favorite: false,
    target: null,
    tapes: [],
    default_copies: 1,
    input_fields: [field()],
    sample: { sn: '274913' },
    ...o,
  };
}

function detail(o: Partial<TemplateDetail> = {}): TemplateDetail {
  const s = summary(o);
  return { ...s, fields: s.input_fields, path: null, definition: {}, tape_reason: null, ...o };
}

describe('Vorlagen', () => {
  it('?vorlage=&werte= wählt die Vorlage und füllt das Feld, Render enthält die Werte', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%22274913%22%7D' });

    const input = await screen.findByLabelText(/Seriennummer/);
    await waitFor(() => expect(input).toHaveValue('274913'));
    await waitFor(() => {
      const call = api.calls.find((c) => c.path === '/api/v1/labels/render');
      expect(call).toBeDefined();
      const body = call?.body as { source: { values: Record<string, string> } };
      expect(body.source.values.sn).toBe('274913');
    });
  });

  it('Pflichtfeld leer: Vorschau mit Beispielwert, ruhiger Hinweis statt Fehler, Drucken gesperrt mit Grund', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail({ input_fields: [field({ default: '' })] }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    // Die Vorschau wird mit dem Beispielwert gerendert, nicht mit dem leeren Feld.
    await waitFor(() => {
      const call = api.calls.find((c) => c.path === '/api/v1/labels/render');
      expect((call?.body as { source: { values: Record<string, string> } } | undefined)?.source.values.sn).toBe('274913');
    });
    expect(await screen.findByText('Beispielinhalt')).toBeInTheDocument();
    expect(screen.getAllByText('Noch auszufüllen: Seriennummer').length).toBeGreaterThan(0);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    const print = screen.getByRole('button', { name: 'Drucken' });
    expect(print).toHaveAttribute('aria-disabled', 'true');

    // Kein Hinweis am Feld, bevor es berührt wurde; „Jetzt ausfüllen“ zeigt ihn und springt hin.
    const input = screen.getByLabelText(/Seriennummer/);
    expect(screen.queryByText('Bitte Seriennummer eingeben')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Jetzt ausfüllen' }));
    expect(await screen.findByText('Bitte Seriennummer eingeben')).toBeInTheDocument();
    expect(input).toHaveFocus();

    // Ausfüllen gibt Drucken frei, Beispiel-Hinweis verschwindet.
    await user.type(input, 'A1');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).not.toHaveAttribute('aria-disabled', 'true'));
    expect(screen.queryByText('Beispielinhalt')).not.toBeInTheDocument();
    expect(screen.getByText('Bereit zum Drucken')).toBeInTheDocument();
  });

  it('Liste zeigt Titel und eine Zeile Beschreibung je Vorlage', async () => {
    mockNarrowScreen(false);
    mockApi({
      'GET /api/v1/templates': () => ({
        templates: [summary({ title: 'Datenträger', description: 'SSD- und HDD-Etiketten. Mit Seriennummer.' })],
      }),
      'GET /api/v1/templates/:name': () => detail({ title: 'Datenträger' }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    const list = await screen.findByRole('group', { name: 'Vorlagen' });
    const item = await within(list).findByRole('button', { name: 'Datenträger' });
    expect(item).toHaveAccessibleDescription('SSD- und HDD-Etiketten');
    expect(item).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('heading', { level: 1, name: 'Datenträger' })).toBeInTheDocument();
  });

  it('Druckoptionen sind eingeklappt, zeigen eine Zusammenfassung und klappen auf', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    const toggle = await screen.findByRole('button', { name: /Druckoptionen/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveTextContent('1 Kopie · Schneidpause Standard');
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByRole('spinbutton')).toBeInTheDocument();
  });

  it('tape_reason zeigt MessageBar; Drucken mit bestätigung_nötig zeigt Rückfrage', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail({ tape_reason: 'Band ungeeignet für diese Vorlage', input_fields: [field({ default: 'A1', required: false })] }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'bestätigung_nötig', reasons: ['Band ungeeignet'] }),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    expect(await screen.findByText(/Band ungeeignet für diese Vorlage/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Wirklich drucken?')).toBeInTheDocument();
  });

  it('sensibles Feld ist Passwortfeld', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail({ input_fields: [field({ id: 'pw', label: 'Passwort', secret: true, required: false })] }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    const input = await screen.findByLabelText(/Passwort/);
    expect(input).toHaveAttribute('type', 'password');
  });

  it('„Belegung exportieren“ nur bei kind: generator sichtbar', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail({ kind: 'layout', input_fields: [field({ required: false })] }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    await screen.findByRole('button', { name: 'Drucken' });
    await user.click(await screen.findByRole('button', { name: /^Weitere Aktionen für / }));
    expect(await screen.findByRole('menuitem', { name: 'Im Editor öffnen' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Belegung exportieren' })).not.toBeInTheDocument();
  });

  it('Belegung exportieren sichtbar bei kind: generator', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary({ kind: 'generator' })] }),
      'GET /api/v1/templates/:name': () => detail({ kind: 'generator', input_fields: [field({ required: false })] }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    await user.click(await screen.findByRole('button', { name: /^Weitere Aktionen für / }));
    expect(await screen.findByRole('menuitem', { name: 'Belegung exportieren' })).toBeInTheDocument();
  });

  it('zeigt „Gekürzt: …“ für Felder aus render.shortened', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson({ shortened: ['sn'] }),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%22274913%22%7D' });

    expect(await screen.findByText('Gekürzt: Seriennummer')).toBeInTheDocument();
  });

  it('zeigt keinen Kürzungs-Hinweis, wenn render.shortened leer ist', async () => {
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson({ shortened: [] }),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    await screen.findByRole('button', { name: 'Drucken' });
    expect(screen.queryByText(/Gekürzt:/)).not.toBeInTheDocument();
  });

  it('ist bei schmaler Breite responsiv: Combobox statt Knopf-Liste, ein-spaltiges Layout', async () => {
    mockNarrowScreen(true);
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    expect(await screen.findByLabelText('Vorlage wählen')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Datentraeger' })).not.toBeInTheDocument();
    const listCol = screen.getByRole('group', { name: 'Vorlagen' });
    const layout = listCol.parentElement as HTMLElement;
    await waitFor(() => expect(getComputedStyle(layout).gridTemplateColumns).toBe('1fr'));
  });

  it('zeigt bei breitem Bildschirm die Knopf-Liste je Kategorie und das drei-spaltige Layout', async () => {
    mockNarrowScreen(false);
    mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });

    expect(await screen.findByRole('button', { name: 'Datentraeger' })).toBeInTheDocument();
    const listCol = screen.getByRole('group', { name: 'Vorlagen' });
    const layout = listCol.parentElement as HTMLElement;
    expect(getComputedStyle(layout).gridTemplateColumns).not.toBe('1fr');
  });

  it('Löschen einer eigenen Vorlage ruft nach Bestätigung DELETE auf', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary({ builtin: false })] }),
      'GET /api/v1/templates/:name': () => detail({ builtin: false, input_fields: [field({ required: false })] }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'DELETE /api/v1/templates/:name': () => ({}),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    await screen.findByRole('button', { name: /^Weitere Aktionen für / });
    await chooseRowAction(user, 'Datentraeger', 'Löschen');
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Löschen', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/templates/datentraeger')).toBe(true));
  });
  it('?import=<id> ohne vorlage: keine Auto-Auswahl, Dialog offen mit Vorlagenwahl, Plan erst nach Wahl', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary({ name: 'datentraeger' }), summary({ name: 'kabel' })] }),
      'GET /api/v1/templates/:name': ({ params }) => detail({ name: params.name }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1']], source_name: 'Import' }),
      'POST /api/v1/batch/plan': () => ({ count: 1, summary: 'ok', mapping: { sn: 'SN' }, headers: ['SN'], warnings: [], errors: [], previews: [] }),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?import=abc' });

    const choice = await screen.findByRole('combobox', { name: 'Zielvorlage' });
    expect(choice).toHaveValue('');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/table')).toBe(true));
    await new Promise((r) => setTimeout(r, 400));
    expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(false);
    expect(api.calls.some((c) => c.method === 'GET' && c.path.startsWith('/api/v1/templates/'))).toBe(false);

    await user.click(choice);
    await user.click(screen.getByRole('option', { name: 'kabel' }));

    await waitFor(
      () => {
        const call = api.calls.find((c) => c.path === '/api/v1/batch/plan');
        expect(call).toBeDefined();
        const body = call?.body as { template: string; source: unknown };
        expect(body.template).toBe('kabel');
        expect(body.source).toEqual({ type: 'pending', id: 'abc' });
      },
      { timeout: 2000 },
    );
  });

  it('?import=<id>&vorlage=<name>: Dialog offen ohne Vorlagenwahl, Plan mit dieser Vorlage', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary({ name: 'datentraeger' }), summary({ name: 'kabel' })] }),
      'GET /api/v1/templates/:name': ({ params }) => detail({ name: params.name }),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1']], source_name: 'Import' }),
      'POST /api/v1/batch/plan': () => ({ count: 1, summary: 'ok', mapping: { sn: 'SN' }, headers: ['SN'], warnings: [], errors: [], previews: [] }),
    });
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?import=abc&vorlage=kabel' });

    await waitFor(
      () => {
        const call = api.calls.find((c) => c.path === '/api/v1/batch/plan');
        expect((call?.body as { template: string } | undefined)?.template).toBe('kabel');
      },
      { timeout: 2000 },
    );
    expect(screen.queryByRole('combobox', { name: 'Zielvorlage' })).not.toBeInTheDocument();
  });
  it('Vorlagenliste mit Kategorie-Überschriften, Suche filtert nach Name, Stichwort und Beschreibung', async () => {
    mockNarrowScreen(false);
    mockApi({
      'GET /api/v1/templates': () => ({
        templates: [
          summary(),
          summary({ name: 'kabel', category: 'Kabel', description: 'Fahnen für Netzwerkkabel', tags: ['lan'] }),
          summary({ name: 'regal', category: 'Lager', description: 'Fachbeschriftung', tags: ['holz'] }),
        ],
      }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    const list = await screen.findByRole('group', { name: 'Vorlagen' });
    expect(within(list).getByRole('heading', { name: 'Kabel' })).toBeInTheDocument();
    expect(within(list).getByRole('heading', { name: 'Lager' })).toBeInTheDocument();
    const search = screen.getByRole('searchbox', { name: 'Vorlagen durchsuchen' });

    await user.type(search, 'LAN');
    await waitFor(() => expect(within(list).queryByRole('button', { name: 'Regal' })).not.toBeInTheDocument());
    expect(within(list).getByRole('button', { name: 'Kabel' })).toBeInTheDocument();
    expect(within(list).queryByRole('heading', { name: 'Lager' })).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'fachbeschr');
    await waitFor(() => expect(within(list).getByRole('button', { name: 'Regal' })).toBeInTheDocument());
    expect(within(list).queryByRole('button', { name: 'Kabel' })).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'datentr');
    await waitFor(() => expect(within(list).getByRole('button', { name: 'Datentraeger' })).toBeInTheDocument());
    expect(within(list).queryByRole('button', { name: 'Regal' })).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'gibtesnicht');
    expect(await within(list).findByText('Keine passende Vorlage')).toBeInTheDocument();
  });

  it.each(['PNG', 'PDF', 'PBM'])('Export als %s ruft exportLabel mit diesem Format', async (label) => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    URL.revokeObjectURL = vi.fn();
    // Download-Link nicht wirklich anklicken (jsdom kennt keine Navigation)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    try {
      const api = mockApi({
        'GET /api/v1/templates': () => ({ templates: [summary()] }),
        'GET /api/v1/templates/:name': () => detail(),
        'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
        'POST /api/v1/labels/render': () => fixtures.renderJson(),
        'POST /api/v1/labels/export': () => new MockResponse(200, 'DATA', { 'Content-Type': 'application/octet-stream' }),
      });
      const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%221%22%7D' });
      await screen.findByLabelText(/Seriennummer/);
      await user.click(screen.getByRole('button', { name: 'Exportieren' }));
      await user.click(await screen.findByRole('menuitem', { name: label }));
      await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/export')).toBe(true));
      const call = api.calls.find((c) => c.path === '/api/v1/labels/export');
      const body = call?.body as { format: string; source: { template: string } };
      expect(body.format).toBe(label.toLowerCase());
      expect(body.source.template).toBe('datentraeger');
      await waitFor(() => expect(clickSpy).toHaveBeenCalled());
    } finally {
      clickSpy.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });

  it('Plausi-Konflikt: Klick auf Drucken öffnet die Bestätigung, Abbrechen druckt nicht, Trotzdem drucken druckt', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({
        findings: [{ level: 'konflikt', field: 'sn', code: 'sn_anderer_host', message: 'SN gehört zu pmx20' }],
        worst: 'konflikt',
      }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, {
      route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%22ABC123%22%7D',
    });
    await screen.findByLabelText(/Seriennummer/);
    await waitFor(() => expect(screen.getByText('SN gehört zu pmx20')).toBeInTheDocument(), { timeout: 5000 });

    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Konflikt bei der Prüfung')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);

    // hidden: true, weil der eben geschlossene Dialog unter voller Parallellast (Tabster) die
    // Seite kurzzeitig noch als aria-hidden markieren kann, obwohl sie sichtbar ist.
    await user.click(screen.getByRole('button', { name: 'Drucken', hidden: true }));
    const dialog2 = await findDialogByRole('alertdialog');
    await user.click(within(dialog2).getByRole('button', { name: 'Trotzdem drucken', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
  });

  it('Plausi-Konflikt: Drucken vor Ende der entprellten Prüfung prüft sofort und fragt nach', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({
        findings: [{ level: 'konflikt', field: 'sn', code: 'sn_anderer_host', message: 'SN gehört zu pmx20' }],
        worst: 'konflikt',
      }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, {
      route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%22ABC123%22%7D',
    });
    await screen.findByLabelText(/Seriennummer/);
    const button = await screen.findByRole('button', { name: 'Drucken' });
    await waitFor(() => expect(button).toBeEnabled());
    // Die entprellte Prüfung (600 ms) ist noch nicht gelaufen: kein Konflikt angezeigt.
    expect(api.calls.some((c) => c.path === '/api/v1/homelab/plausi')).toBe(false);

    await user.click(button);
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Konflikt bei der Prüfung')).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(false);
  });

  it('Plausi-Warnung: Druck ohne Bestätigung', async () => {
    const api = mockApi({
      'GET /api/v1/templates': () => ({ templates: [summary()] }),
      'GET /api/v1/templates/:name': () => detail(),
      'POST /api/v1/homelab/plausi': () => ({
        findings: [{ level: 'warnung', field: 'sn', code: 'sn_kuerzung_mehrdeutig', message: 'Kürzung mehrdeutig' }],
        worst: 'warnung',
      }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson(),
    });
    const { user } = renderWithProviders(<VorlagenPage />, {
      route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%22ABC123%22%7D',
    });
    await screen.findByLabelText(/Seriennummer/);
    await waitFor(() => expect(screen.getByText('Kürzung mehrdeutig')).toBeInTheDocument(), { timeout: 5000 });

    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });
});
