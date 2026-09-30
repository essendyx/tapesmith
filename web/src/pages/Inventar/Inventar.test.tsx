import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { MockResponse, findDialog, fixtures, mockApi, mockNarrowScreen, renderWithProviders } from '../../test/utils';
import type { BoxDetailJson, BoxJson, LoanJson, SearchHitJson } from '../../api/types';
import InventarPage from '.';

const box1: BoxJson = { id: 'BOX-07', location: 'Keller Regal 2', note: '', created: '2026-09-01T10:00:00', items: 2 };
const box2: BoxJson = { id: 'BOX-08', location: 'Keller Regal 3', note: '', created: '2026-09-01T10:00:00', items: 0 };

const boxDetail: BoxDetailJson = {
  ...box1,
  item_list: [
    { id: 1, box_id: 'BOX-07', name: 'HDMI-Adapter', qty: 1, note: '' },
    { id: 2, box_id: 'BOX-07', name: 'Netzkabel', qty: 3, note: '' },
  ],
};

function boxesHandlers() {
  return {
    'GET /api/v1/inventory/boxes': () => ({ boxes: [box1, box2] }),
    'GET /api/v1/inventory/boxes/:id': ({ params }: { params: Record<string, string> }) =>
      params.id === 'BOX-07' ? boxDetail : { ...box2, item_list: [] },
  };
}

describe('InventarPage', () => {
  it('Box anlegen sendet POST /inventory/boxes mit {id, location, note}; 422 zeigt Meldung im Dialog', async () => {
    let attempt = 0;
    const api = mockApi({
      ...boxesHandlers(),
      'POST /api/v1/inventory/boxes': ({ body }) => {
        attempt += 1;
        if (attempt === 1) {
          return new MockResponse(422, {
            error: { kind: 'Validierung', message: 'Box-ID bereits vergeben', hint: '', exit_code: 1, details: null },
          });
        }
        return { ...(body as object), created: '2026-09-28T09:00:00', items: 0 } as BoxJson;
      },
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await screen.findByText('BOX-07');
    await user.click(screen.getByRole('button', { name: 'Neue Box' }));
    const dialog = await findDialog('Neue Box');
    await user.type(within(dialog).getByLabelText('Box-ID'), 'BOX-09');
    await user.type(within(dialog).getByLabelText('Ort'), 'Dachboden');
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen' }));
    await screen.findByText('Box-ID bereits vergeben');

    await user.clear(within(dialog).getByLabelText('Box-ID'));
    await user.type(within(dialog).getByLabelText('Box-ID'), 'BOX-10');
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    const create = api.calls.filter((c) => c.path === '/api/v1/inventory/boxes' && c.method === 'POST');
    expect(create).toHaveLength(2);
    expect(create[1]?.body).toEqual({ id: 'BOX-10', location: 'Dachboden', note: '' });
  });

  it('Suche zeigt Treffertext', async () => {
    const hit: SearchHitJson = { item: { id: 1, box_id: 'BOX-07', name: 'HDMI-Adapter', qty: 1, note: '' }, box: box1, text: 'HDMI-Adapter · BOX-07, Keller Regal 2' };
    mockApi({
      ...boxesHandlers(),
      'GET /api/v1/inventory/search': () => ({ hits: [hit] }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=suche' });
    await user.type(screen.getByLabelText('Was suchst du?'), 'HDMI');
    expect(await screen.findByText('HDMI-Adapter · BOX-07, Keller Regal 2')).toBeInTheDocument();
  });

  it('Verleih mit overdue: true zeigt Badge „überfällig"; „Zurückgegeben" sendet POST /inventory/loans/<id>/return', async () => {
    const loan: LoanJson = { id: 5, item: 'Bohrmaschine', person: 'Hubert', since: '2026-09-01T00:00:00', due: '2026-09-10', returned: null, note: '', open: true, overdue: true };
    const api = mockApi({
      ...boxesHandlers(),
      'GET /api/v1/inventory/loans': () => ({ loans: [loan] }),
      'POST /api/v1/inventory/loans/:id/return': () => ({ ...loan, open: false, overdue: false, returned: '2026-09-28' }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
    expect(await screen.findByText('überfällig')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Zurückgegeben: / }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/inventory/loans/5/return' && c.method === 'POST')).toBe(true));
  });

  it('Box-Label-Dialog rendert (labels/render mit {type: "box", box_id}) und druckt (labels/print mit denselben Feldern plus options)', async () => {
    const api = mockApi({
      ...boxesHandlers(),
      'POST /api/v1/inventory/labels/render': () => fixtures.renderJson({ title: 'Box BOX-07' }),
      'POST /api/v1/inventory/labels/print': () => fixtures.outcomeJson({ title: 'Box BOX-07' }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await user.click(await screen.findByText('BOX-07'));
    await user.click(await screen.findByRole('button', { name: 'Box-Label' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/inventory/labels/render')).toBe(true));
    const renderCall = api.calls.find((c) => c.path === '/api/v1/inventory/labels/render');
    expect(renderCall?.body).toEqual({ type: 'box', box_id: 'BOX-07' });

    const labelDialog = await findDialog('Box-Label');
    await user.click(within(labelDialog).getByRole('button', { name: 'Drucken', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/inventory/labels/print')).toBe(true));
    const printCall = api.calls.find((c) => c.path === '/api/v1/inventory/labels/print');
    const printBody = printCall?.body as { type: string; box_id: string; options: unknown };
    expect(printBody.type).toBe('box');
    expect(printBody.box_id).toBe('BOX-07');
    expect(printBody.options).toBeTruthy();
  });

  it('?tab=verleih öffnet den Reiter Verleih', async () => {
    mockApi({ ...boxesHandlers(), 'GET /api/v1/inventory/loans': () => ({ loans: [] }) });
    renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
    expect(await screen.findByText('Nichts verliehen')).toBeInTheDocument();
  });

  it('Box-Detail: fehlschlagender Aufruf (500) zeigt eine Meldung statt einer unhandled rejection', async () => {
    mockApi({
      ...boxesHandlers(),
      'PUT /api/v1/inventory/boxes/:id': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Speichern fehlgeschlagen', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await user.click(await screen.findByText('BOX-07'));
    const dialog = await findDialog('Box BOX-07');
    await user.type(within(dialog).getByLabelText('Ort'), 'X');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern' }));
    expect(await screen.findByText('Speichern fehlgeschlagen')).toBeInTheDocument();
    // Dialog bleibt offen, kein stiller Fehlschlag
    expect(screen.getByText('Box BOX-07', { selector: '.fui-DialogTitle' })).toBeInTheDocument();
  });

  it('Box-Detail: Gegenstand hinzufuegen zeigt bei 422 eine Meldung', async () => {
    mockApi({
      ...boxesHandlers(),
      'POST /api/v1/inventory/items': () =>
        new MockResponse(422, { error: { kind: 'Validierung', message: 'Name fehlt', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await user.click(await screen.findByText('BOX-07'));
    const dialog = await findDialog('Box BOX-07');
    await user.type(within(dialog).getByLabelText('Name'), 'Kabel');
    await user.click(within(dialog).getByRole('button', { name: 'Hinzufügen' }));
    expect(await screen.findByText('Name fehlt')).toBeInTheDocument();
  });

  it('Verleih: fehlschlagendes Verleihen (422) zeigt eine Meldung, Dialog bleibt offen', async () => {
    mockApi({
      ...boxesHandlers(),
      'GET /api/v1/inventory/loans': () => ({ loans: [] }),
      'POST /api/v1/inventory/loans': () =>
        new MockResponse(422, { error: { kind: 'Validierung', message: 'Person fehlt', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
    await screen.findByText('Nichts verliehen');
    await user.click(screen.getByRole('button', { name: 'Verleihen' }));
    const dialog = await findDialog('Verleihen');
    await user.type(within(dialog).getByLabelText('Gegenstand'), 'Bohrmaschine');
    await user.type(within(dialog).getByLabelText('An wen?'), 'Hubert');
    await user.click(within(dialog).getByRole('button', { name: 'Verleihen' }));
    expect(await screen.findByText('Person fehlt')).toBeInTheDocument();
    expect(screen.getByText('Verleihen', { selector: '.fui-DialogTitle' })).toBeInTheDocument();
  });

  it('Verleih: fehlschlagendes „Zurückgegeben" (500) zeigt eine Meldung', async () => {
    const loan: LoanJson = { id: 5, item: 'Bohrmaschine', person: 'Hubert', since: '2026-09-01T00:00:00', due: null, returned: null, note: '', open: true, overdue: false };
    mockApi({
      ...boxesHandlers(),
      'GET /api/v1/inventory/loans': () => ({ loans: [loan] }),
      'POST /api/v1/inventory/loans/:id/return': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Rückgabe fehlgeschlagen', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
    await user.click(await screen.findByRole('button', { name: /^Zurückgegeben: / }));
    expect(await screen.findByText('Rückgabe fehlgeschlagen')).toBeInTheDocument();
  });

  it('Suche: fehlschlagender Request (500) zeigt eine Meldung statt stillem Fehlschlag', async () => {
    mockApi({
      ...boxesHandlers(),
      'GET /api/v1/inventory/search': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Suche fehlgeschlagen', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=suche' });
    await user.type(screen.getByLabelText('Was suchst du?'), 'HDMI');
    expect(await screen.findAllByText('Suche fehlgeschlagen')).not.toHaveLength(0);
  });
  it('Boxen: fehlschlagender initialer Request (500) zeigt eine Meldung statt leerem Raster', async () => {
    mockApi({
      'GET /api/v1/inventory/boxes': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Boxen nicht lesbar', hint: 'Datenbank pruefen', exit_code: 1, details: null } }),
    });
    renderWithProviders(<InventarPage />, { route: '/inventar' });
    expect(await screen.findByText('Boxen nicht lesbar')).toBeInTheDocument();
    expect(screen.getByText('Datenbank pruefen')).toBeInTheDocument();
    expect(screen.queryByText('Noch keine Box')).not.toBeInTheDocument();
  });

  it('Label-Dialog: fehlschlagendes labels/render (500) zeigt eine Meldung', async () => {
    mockApi({
      ...boxesHandlers(),
      'POST /api/v1/inventory/labels/render': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Vorschau fehlgeschlagen', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await user.click(await screen.findByText('BOX-07'));
    await user.click(await screen.findByRole('button', { name: 'Box-Label' }));
    expect(await screen.findAllByText('Vorschau fehlgeschlagen')).not.toHaveLength(0);
  });
  it('Label-Dialog ersetzt den Box-Dialog, nie zwei modale Dialoge gleichzeitig', async () => {
    mockApi({
      ...boxesHandlers(),
      'POST /api/v1/inventory/labels/render': () => fixtures.renderJson({ title: 'Box BOX-07' }),
    });
    const { user } = renderWithProviders(<InventarPage />, { route: '/inventar' });
    await user.click(await screen.findByText('BOX-07'));
    await findDialog('Box BOX-07');
    await user.click(await screen.findByRole('button', { name: 'Inhaltslabel' }));

    const labelDialog = await findDialog('Inhaltslabel');
    await waitFor(() => expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1));
    expect(screen.queryByText('Box BOX-07', { selector: '.fui-DialogTitle' })).not.toBeInTheDocument();

    await user.click(within(labelDialog).getByRole('button', { name: 'Schließen', hidden: true }));
    await findDialog('Box BOX-07');
    await waitFor(() => expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1));
    expect(screen.queryByText('Inhaltslabel', { selector: '.fui-DialogTitle' })).not.toBeInTheDocument();
  });
  it('Verleih bei schmaler Breite als Karten statt Tabelle, Aktionen bleiben bedienbar', async () => {
    const restore = mockNarrowScreen(true);
    try {
      const loan: LoanJson = { id: 5, item: 'Bohrmaschine', person: 'Hubert', since: '2026-09-01T00:00:00', due: '2026-09-10', returned: null, note: '', open: true, overdue: true };
      const api = mockApi({
        ...boxesHandlers(),
        'GET /api/v1/inventory/loans': () => ({ loans: [loan] }),
        'POST /api/v1/inventory/loans/:id/return': () => ({ ...loan, open: false, overdue: false, returned: '2026-09-28' }),
      });
      const { user } = renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
      const list = await screen.findByRole('list', { name: 'Verleihliste' });
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      const card = within(list).getByRole('listitem');
      expect(within(card).getByText('Bohrmaschine')).toBeInTheDocument();
      expect(within(card).getByText('Hubert')).toBeInTheDocument();
      expect(within(card).getByText('überfällig')).toBeInTheDocument();
      await user.click(within(card).getByRole('button', { name: /^Zurückgegeben: / }));
      await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/inventory/loans/5/return')).toBe(true));
    } finally {
      restore();
    }
  });

  it('Verleih bei breitem Bildschirm Tabelle in eigenem, seitlich scrollbarem Container', async () => {
    const restore = mockNarrowScreen(false);
    try {
      const loan: LoanJson = { id: 5, item: 'Bohrmaschine', person: 'Hubert', since: '2026-09-01T00:00:00', due: null, returned: null, note: '', open: true, overdue: false };
      mockApi({ ...boxesHandlers(), 'GET /api/v1/inventory/loans': () => ({ loans: [loan] }) });
      renderWithProviders(<InventarPage />, { route: '/inventar?tab=verleih' });
      const table = await screen.findByRole('table', { name: 'Verleihliste' });
      expect(getComputedStyle(table.parentElement as HTMLElement).overflowX).toBe('auto');
    } finally {
      restore();
    }
  });
});
