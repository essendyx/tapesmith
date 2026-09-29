import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { findDialogByRole, fixtures, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { BatchPlanJson, BatchRequest, FieldJson } from '../../api/types';
import { BatchDialog } from './BatchDialog';

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

const fieldSn = field({ id: 'sn', label: 'SN' });
const fieldHost = field({ id: 'host', label: 'Host', required: false });

function plan(o: Partial<BatchPlanJson> = {}): BatchPlanJson {
  return {
    count: 1,
    summary: 'Bandbilanz: 1 Etikett, 25 mm',
    mapping: { sn: 'SN', host: 'Host' },
    headers: ['SN', 'Host'],
    warnings: [],
    errors: [],
    previews: [],
    ...o,
  };
}

describe('BatchDialog', () => {
  it('Text einfügen ruft /batch/table und /batch/plan; Zuordnung vorbelegt; Zusammenfassung sichtbar', async () => {
    const api = mockApi({
      'POST /api/v1/batch/table': () => ({ headers: ['SN', 'Host'], rows: [['A1', 'pmx10']], source_name: 'Einfügung' }),
      'POST /api/v1/batch/plan': () => plan(),
    });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn, fieldHost]} />,
    );

    await user.type(screen.getByLabelText('Tabelle einfügen'), 'SN;Host{Enter}A1;pmx10');

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/table')).toBe(true));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(true), { timeout: 2000 });

    expect(await screen.findByTestId('batch-summary')).toHaveTextContent('Bandbilanz: 1 Etikett, 25 mm');
    await waitFor(() => expect(screen.getByLabelText('Zuordnung SN')).toHaveValue('SN'));
  });

  it('Zeile abwählen: nächster Plan hat selected ohne diese Zeile', async () => {
    const api = mockApi({
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1'], ['A2']], source_name: 'x' }),
      'POST /api/v1/batch/plan': () => plan({ count: 2 }),
    });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    await user.type(screen.getByLabelText('Tabelle einfügen'), 'SN{Enter}A1{Enter}A2');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(true), { timeout: 2000 });
    api.calls.length = 0;

    await user.click(screen.getByLabelText('Zeile 1 auswählen'));

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(true), { timeout: 2000 });
    const call = api.calls.find((c) => c.path === '/api/v1/batch/plan');
    const body = call?.body as BatchRequest;
    expect(body.selected).toEqual([1]);
  });

  it('Reiter Serie mit 1..5: Plan-Anfrage hat source.type "series"', async () => {
    const api = mockApi({ 'POST /api/v1/batch/plan': () => plan() });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    await user.click(screen.getByRole('tab', { name: 'Serie' }));
    await user.type(screen.getByPlaceholderText('z. B. 1..24'), '1..5');

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(true), { timeout: 2000 });
    const call = api.calls.find((c) => c.path === '/api/v1/batch/plan');
    const body = call?.body as BatchRequest;
    expect(body.source.type).toBe('series');
  });

  it('errors nicht leer deaktiviert den Drucken-Knopf', async () => {
    mockApi({ 'POST /api/v1/batch/plan': () => plan({ errors: ['Zeile 1: Feld sn fehlt'] }) });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    await user.click(screen.getByRole('tab', { name: 'Liste' }));
    await user.type(screen.getByLabelText('Eine Zeile pro Label'), 'A1');
    await waitFor(() => expect(screen.getByTestId('batch-summary')).toBeInTheDocument(), { timeout: 2000 });
    expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled();
  });

  it('errors leer druckt mit chain aus dem Schalter', async () => {
    const api = mockApi({
      'POST /api/v1/batch/plan': () => plan({ errors: [] }),
      'POST /api/v1/batch/print': () => fixtures.outcomeJson(),
    });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    await user.click(screen.getByRole('tab', { name: 'Liste' }));
    await user.type(screen.getByLabelText('Eine Zeile pro Label'), 'A1');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled(), { timeout: 2000 });

    await user.click(screen.getByLabelText('Als Kette'));
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/batch/print');
    expect((call?.body as BatchRequest & { options: { chain: boolean } }).options.chain).toBe(true);
  });

  it.each([
    ['5 s', 5],
    ['keine', -1],
    ['bis „Weiter“', 0],
  ])('Schneidpause %s wird an den Druck übergeben', async (label, expected) => {
    const api = mockApi({
      'POST /api/v1/batch/plan': () => plan({ errors: [] }),
      'POST /api/v1/batch/print': () => fixtures.outcomeJson(),
    });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    await user.click(screen.getByRole('tab', { name: 'Liste' }));
    await user.type(screen.getByLabelText('Eine Zeile pro Label'), 'A1');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled(), { timeout: 2000 });

    expect(screen.queryByRole('spinbutton', { name: 'Kopien' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: 'Schneidpause' }));
    await user.click(await screen.findByRole('option', { name: label }));
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/batch/print');
    expect((call?.body as BatchRequest & { options: { cut_pause_s: number | null } }).options.cut_pause_s).toBe(expected);
  });

  it('?import=abc: Dialog offen, Plan-Anfrage mit source pending id abc', async () => {
    const api = mockApi({
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1']], source_name: 'Import' }),
      'POST /api/v1/batch/plan': () => plan(),
    });
    renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} initialImport="abc" />,
    );
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(true), { timeout: 2000 });
    const call = api.calls.find((c) => c.path === '/api/v1/batch/plan');
    const body = call?.body as BatchRequest;
    expect(body.source).toEqual({ type: 'pending', id: 'abc' });
  });

  it('Datei-Upload (.csv): Tabelle und Plan laufen mit source.type "file" und den echten Dateidaten', async () => {
    const api = mockApi({
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1'], ['A2']], source_name: 'datei.csv' }),
      'POST /api/v1/batch/plan': () => plan({ count: 2 }),
    });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    const file = new File(['SN\nA1\nA2\n'], 'datei.csv', { type: 'text/csv' });
    await user.upload(screen.getByLabelText('Datei hochladen'), file);

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(true), { timeout: 2000 });
    const expected = { type: 'file', name: 'datei.csv', data_b64: btoa('SN\nA1\nA2\n'), has_header: null };
    const table = api.calls.filter((c) => c.path === '/api/v1/batch/table').at(-1);
    expect((table?.body as { source: unknown }).source).toEqual(expected);
    const planCall = api.calls.filter((c) => c.path === '/api/v1/batch/plan').at(-1);
    expect((planCall?.body as BatchRequest).source).toEqual(expected);
    expect(screen.getByTestId('batch-datei')).toHaveTextContent('datei.csv');
    expect(api.calls.some((c) => JSON.stringify(c.body ?? null).includes('__datei__'))).toBe(false);
  });

  it('Datei-Upload, danach Text tippen: Quelle ist wieder Text statt Datei', async () => {
    const api = mockApi({
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1']], source_name: 'x' }),
      'POST /api/v1/batch/plan': () => plan(),
    });
    const { user } = renderWithProviders(
      <BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />,
    );
    await user.upload(screen.getByLabelText('Datei hochladen'), new File(['SN\nA1\n'], 'datei.csv', { type: 'text/csv' }));
    await waitFor(() => expect(screen.getByTestId('batch-datei')).toBeInTheDocument());

    await user.type(screen.getByLabelText('Tabelle einfügen'), 'Z9');
    await waitFor(
      () => {
        const last = api.calls.filter((c) => c.path === '/api/v1/batch/plan').at(-1);
        expect((last?.body as BatchRequest | undefined)?.source).toEqual({ type: 'text', text: 'Z9', has_header: null });
      },
      { timeout: 2000 },
    );
    expect(screen.queryByTestId('batch-datei')).not.toBeInTheDocument();
  });

  it('ohne Vorlage: Vorlagenwahl sichtbar, kein Plan; Auswahl meldet den Namen', async () => {
    const api = mockApi({
      'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1']], source_name: 'Import' }),
      'POST /api/v1/batch/plan': () => plan(),
    });
    const onSelect = vi.fn();
    const { user } = renderWithProviders(
      <BatchDialog
        open
        onOpenChange={() => undefined}
        templateName={null}
        fields={[]}
        initialImport="abc"
        templates={['datentraeger', 'kabel']}
        onSelectTemplate={onSelect}
      />,
    );
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/batch/table')).toBe(true));
    await new Promise((r) => setTimeout(r, 400));
    expect(api.calls.some((c) => c.path === '/api/v1/batch/plan')).toBe(false);

    await user.click(screen.getByRole('combobox', { name: 'Zielvorlage' }));
    await user.click(screen.getByRole('option', { name: 'kabel' }));
    expect(onSelect).toHaveBeenCalledWith('kabel');
  });

  it('ist auf schmalen Bildschirmen (<= 599 px) Vollbild', async () => {
    mockNarrowScreen(true);
    mockApi({ 'POST /api/v1/batch/plan': () => plan() });
    renderWithProviders(<BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />);
    const surface = await findDialogByRole('dialog');
    await waitFor(() => expect(getComputedStyle(surface).width).toBe('100vw'));
    expect(getComputedStyle(surface).height).toBe('100vh');
  });

  it('ist auf breiten Bildschirmen nicht Vollbild', async () => {
    mockNarrowScreen(false);
    mockApi({ 'POST /api/v1/batch/plan': () => plan() });
    renderWithProviders(<BatchDialog open onOpenChange={() => undefined} templateName="datentraeger" fields={[fieldSn]} />);
    const surface = await findDialogByRole('dialog');
    await waitFor(() => expect(getComputedStyle(surface).width).toBe('95vw'));
  });
});
