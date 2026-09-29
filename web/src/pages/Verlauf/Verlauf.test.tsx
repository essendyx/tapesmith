import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, findDialog, fixtures, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { HistoryEntryJson } from '../../api/types';
import VerlaufPage from './index';

afterEach(() => {
  restoreAllMocks();
  vi.useRealTimers();
});

function entry(o: Partial<HistoryEntryJson> = {}): HistoryEntryJson {
  return {
    id: 1,
    created: '2026-09-27T12:00:00',
    source: 'gui',
    kind: 'text',
    title: 'Server 274913',
    template: null,
    values: {},
    spec: null,
    length_mm: 25,
    tape_mm: 35,
    copies: 2,
    chained: false,
    status: 'ok',
    error: '',
    sensitive: false,
    has_head: true,
    reprintable: true,
    missing_secrets: [],
    ...o,
  };
}

describe('/verlauf', () => {
  it('zeigt die Liste aus GET /history', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry(), entry({ id: 2, title: 'Zweites Label' })] }) });
    renderWithProviders(<VerlaufPage />);
    expect(await screen.findByText('Server 274913')).toBeInTheDocument();
    expect(screen.getByText('Zweites Label')).toBeInTheDocument();
  });

  it('Suche sendet query (entprellt)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    api.calls.length = 0;
    const search = screen.getByRole('textbox', { name: 'Verlauf durchsuchen' });
    await user.type(search, '274913');
    await vi.advanceTimersByTimeAsync(250);
    await vi.waitFor(() => expect(api.calls.some((c) => c.path.includes('query=274913'))).toBe(true));
  });

  it('Erneut drucken bei normalem Eintrag zeigt einen Dialog, vorbelegt mit den Werten des Eintrags, und druckt danach', async () => {
    const api = mockApi({
      'GET /api/v1/history': () => ({ entries: [entry()] }),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ history_id: 9 }),
    });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: /Erneut drucken/ }));
    const dialog = await findDialog('Erneut drucken');
    // hidden: true, weil ein zuvor geschlossener Dialog unter voller Parallellast (Tabster,
    // siehe findDialog) diesen Dialog noch als aria-hidden markieren kann, obwohl er sichtbar ist.
    expect(within(dialog).getByRole('spinbutton', { name: 'Kopien', hidden: true })).toHaveValue(2);
    expect(within(dialog).getByRole('switch', { name: 'Mit Kette drucken', hidden: true })).not.toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: 'Drucken', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { source: { kind: string; id: number }; options: { copies: number; chain: boolean } };
    expect(body.source).toEqual({ kind: 'history', id: 1 });
    expect(body.options.copies).toBe(2);
    expect(body.options.chain).toBe(false);
  });

  it('Erneut drucken übernimmt die Kette eines in Kette gedruckten Eintrags', async () => {
    const api = mockApi({
      'GET /api/v1/history': () => ({ entries: [entry({ chained: true })] }),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({}),
    });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: /Erneut drucken/ }));
    const dialog = await findDialog('Erneut drucken');
    expect(within(dialog).getByRole('switch', { name: 'Mit Kette drucken', hidden: true })).toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: 'Drucken', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { options: { chain: boolean } };
    expect(body.options.chain).toBe(true);
  });

  it('Kopien und Kette im Nachdruck-Dialog sind vor dem Absenden aenderbar', async () => {
    const api = mockApi({
      'GET /api/v1/history': () => ({ entries: [entry({ copies: 1, chained: false })] }),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({}),
    });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: /Erneut drucken/ }));
    const dialog = await findDialog('Erneut drucken');
    const copiesField = within(dialog).getByRole('spinbutton', { name: 'Kopien', hidden: true });
    await user.clear(copiesField);
    await user.type(copiesField, '5');
    await user.click(within(dialog).getByRole('switch', { name: 'Mit Kette drucken', hidden: true }));
    await user.click(within(dialog).getByRole('button', { name: 'Drucken', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { options: { copies: number; chain: boolean } };
    expect(body.options.copies).toBe(5);
    expect(body.options.chain).toBe(true);
  });

  it('fehlende sensible Felder fragen im selben Nachdruck-Dialog ab', async () => {
    const api = mockApi({
      'GET /api/v1/history': () => ({ entries: [entry({ missing_secrets: ['password'] })] }),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({}),
    });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: /Erneut drucken/ }));
    const dialog = await findDialog('Erneut drucken');
    expect(within(dialog).getByRole('spinbutton', { name: 'Kopien', hidden: true })).toBeInTheDocument();
    const passwordField = within(dialog).getByLabelText(/password/i);
    await user.type(passwordField, 'geheim123');
    await user.click(within(dialog).getByRole('button', { name: 'Drucken', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { source: { values?: Record<string, string> } };
    expect(body.source.values?.password).toBe('geheim123');
  });

  it('Im Editor öffnen navigiert nach /editor?verlauf=<id>', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
    const { user } = renderWithProviders(
      <>
        <VerlaufPage />
        <LocationProbe />
      </>,
    );
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: 'Im Editor öffnen: Server 274913' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/editor?verlauf=1');
  });

  it('Als Vorlage speichern ruft from-history und dann POST /templates', async () => {
    const api = mockApi({
      'GET /api/v1/history': () => ({ entries: [entry()] }),
      'POST /api/v1/documents/from-history/:id': () => ({ document: { version: 1, objects: [] } }),
      'POST /api/v1/templates': () => ({}),
    });
    const { user } = renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    await user.click(screen.getByRole('button', { name: 'Als Vorlage speichern: Server 274913' }));
    const dialog = await findDialog('Als Vorlage speichern');
    await user.type(within(dialog).getByLabelText('Name'), 'Servertyp');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/templates')).toBe(true));
    const order = api.calls.map((c) => c.path);
    expect(order.indexOf('/api/v1/history/1/archive')).toBe(-1);
    expect(order.indexOf('/api/v1/documents/from-history/1')).toBeLessThan(order.indexOf('/api/v1/templates'));
    const templateCall = api.calls.find((c) => c.path === '/api/v1/templates');
    const body = templateCall?.body as { name: string; document: unknown };
    expect(body.name).toBe('Servertyp');
    expect(body.document).toEqual({ version: 1, objects: [] });
  });

  it('sensibler Eintrag zeigt ein Schloss statt eines Bildes', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry({ sensitive: true, has_head: false })] }) });
    renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    expect(screen.getByLabelText('sensibler Eintrag, kein Bild gespeichert')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Miniatur' })).not.toBeInTheDocument();
  });

  it('nicht nachdruckbare Einträge deaktivieren „Erneut drucken“', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry({ reprintable: false })] }) });
    renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    expect(screen.getByRole('button', { name: /Erneut drucken/ })).toBeDisabled();
  });

  it('zeigt die Liste auf breiten Bildschirmen als Fluent DataGrid', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
    renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    expect(screen.getByRole('grid', { name: 'Verlaufseinträge' })).toBeInTheDocument();
  });

  it('zeigt die Liste auf schmalen Bildschirmen als Karten statt als DataGrid', async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query.includes('max-width'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia;
    try {
      mockApi({ 'GET /api/v1/history': () => ({ entries: [entry()] }) });
      renderWithProviders(<VerlaufPage />);
      await screen.findByText('Server 274913');
      expect(screen.queryByRole('grid', { name: 'Verlaufseinträge' })).not.toBeInTheDocument();
      expect(screen.getByText('Server 274913').closest('article')).toBeInTheDocument();
    } finally {
      window.matchMedia = original;
    }
  });

  it('fehlendes Bild ohne sensiblen Eintrag zeigt „kein Bild“ statt eines Platzhalterzeichens', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry({ has_head: false, sensitive: false })] }) });
    renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    expect(screen.getByText('kein Bild')).toBeInTheDocument();
  });

  it('Status-Badge zeigt ein Symbol (nicht nur Farbe und Text)', async () => {
    mockApi({ 'GET /api/v1/history': () => ({ entries: [entry({ status: 'ok' })] }) });
    renderWithProviders(<VerlaufPage />);
    await screen.findByText('Server 274913');
    const badge = screen.getByText('ok');
    expect(badge.querySelector('svg')).toBeTruthy();
  });
});
