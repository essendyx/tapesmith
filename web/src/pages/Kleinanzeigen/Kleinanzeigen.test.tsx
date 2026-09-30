import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { chooseRowAction, findDialog, MockResponse, mockApi, renderWithProviders, type MockHandler } from '../../test/utils';
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

const LABEL_ARTIKEL = { template: 'ka-artikel', values: { id: 'KA-001', titel: 'Monitorarm', preis: '25 €', link: 'https://example.org/a/1' }, warnings: [] };
const LABEL_RESERVIERT = { template: 'reserviert', values: { name: 'Hubert', bis: '30.09.2026' }, warnings: [] };

const RENDER_JSON = {
  ok: true, title: 'Etikett', preview: null, errors: [], warnings: [], issues: [], fixes: [], font_size: null,
  qr: null, values: {}, shortened: [], notes: [], tape_reason: null, missing_secrets: [], editor: null,
};

function routes(items: ArtikelJson[], extra: Record<string, MockHandler> = {}): Record<string, MockHandler> {
  return {
    'GET /api/v1/homelab/ka': () => ({ items, next: 'KA-002', shortlink: false }),
    'GET /api/v1/homelab/ka/:id/label': ({ query }) => (query.get('art') === 'reserviert' ? LABEL_RESERVIERT : LABEL_ARTIKEL),
    'POST /api/v1/labels/render': () => RENDER_JSON,
    ...extra,
  };
}

describe('Kleinanzeigen', () => {
  it('zeigt die Liste mit Status', async () => {
    mockApi(
      routes([
        makeArtikel(),
        makeArtikel({ id: 'KA-002', titel: 'Stuhl', status: 'reserviert', name: 'Hubert', datum: '30.09.2026' }),
      ]),
    );
    renderWithProviders(<KleinanzeigenPage />, { route: '/homelab/kleinanzeigen' });

    const list = await screen.findByRole('table', { name: 'Kleinanzeigen-Artikel' });
    expect(within(list).getByText(/KA-001/)).toBeInTheDocument();
    expect(within(list).getByText(/KA-002/)).toBeInTheDocument();
    expect(within(list).getByText('reserviert')).toBeInTheDocument();
    expect(within(list).getByText(/Hubert bis 30.09.2026/)).toBeInTheDocument();
  });

  it('leerer Zustand ohne Artikel', async () => {
    mockApi(routes([]));
    renderWithProviders(<KleinanzeigenPage />, { route: '/homelab/kleinanzeigen' });
    expect(await screen.findByText('Noch kein Artikel angelegt')).toBeInTheDocument();
  });

  it('„Neuer Artikel" sendet POST mit Titel', async () => {
    let sent: unknown = null;
    mockApi(
      routes([], {
        'POST /api/v1/homelab/ka': ({ body }) => {
          sent = body;
          return makeArtikel({ titel: 'Standleuchte' });
        },
      }),
    );
    const { user } = renderWithProviders(<KleinanzeigenPage />, { route: '/homelab/kleinanzeigen' });

    await user.click(await screen.findByRole('button', { name: 'Neuer Artikel' }));
    const dialog = await findDialog('Neuer Artikel');
    await user.type(within(dialog).getByRole('textbox', { name: 'Titel', hidden: true }), 'Standleuchte');
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen', hidden: true }));

    await waitFor(() => expect(sent).toMatchObject({ titel: 'Standleuchte' }));
  });

  it('„Reservieren" sendet status, name und datum', async () => {
    let sent: unknown = null;
    mockApi(
      routes([makeArtikel()], {
        'POST /api/v1/homelab/ka/:id/status': ({ body }) => {
          sent = body;
          return makeArtikel({ status: 'reserviert', name: 'Anna', datum: '01.10.2026' });
        },
      }),
    );
    const { user } = renderWithProviders(<KleinanzeigenPage />, { route: '/homelab/kleinanzeigen' });

    await screen.findByText('Monitorarm');
    await chooseRowAction(user, 'KA-001 Monitorarm', 'Reservieren');
    const dialog = await findDialog('Reservieren');
    await user.type(within(dialog).getByRole('textbox', { name: 'Name', hidden: true }), 'Anna');
    await user.click(within(dialog).getByRole('button', { name: 'Reservieren', hidden: true }));

    await waitFor(() =>
      expect(sent).toMatchObject({ status: 'reserviert', name: 'Anna' }),
    );
    expect((sent as { datum: string }).datum).toEqual(expect.any(String));
    expect((sent as { datum: string }).datum.length).toBeGreaterThan(0);
  });

  it('„Reserviert-Etikett drucken" sendet labels/print mit template reserviert', async () => {
    let sent: unknown = null;
    mockApi(
      routes([makeArtikel({ status: 'reserviert', name: 'Hubert', datum: '30.09.2026' })], {
        'POST /api/v1/labels/print': ({ body }) => {
          sent = body;
          return {
            status: 'ok', warnings: [], reasons: [], history_id: 1, consumed_mm: 10, results: [],
            printer_status: null, error: null, queue_id: null, job_key: 'k', title: 'Etikett', balance_text: '',
          };
        },
      }),
    );
    const { user } = renderWithProviders(<KleinanzeigenPage />, { route: '/homelab/kleinanzeigen' });

    await screen.findByText('Monitorarm');
    await chooseRowAction(user, 'KA-001 Monitorarm', 'Reserviert-Etikett drucken');

    await waitFor(() => expect(sent).not.toBeNull());
    expect((sent as { source: { template: string } }).source.template).toBe('reserviert');
  });

  it('422-Fehler beim Anlegen zeigt die Meldung', async () => {
    mockApi(
      routes([], {
        'POST /api/v1/homelab/ka': () =>
          new MockResponse(422, {
            error: { kind: 'ValueError', message: 'Titel darf nicht leer sein', hint: '', exit_code: 1, details: null },
          }),
      }),
    );
    const { user } = renderWithProviders(<KleinanzeigenPage />, { route: '/homelab/kleinanzeigen' });

    await user.click(await screen.findByRole('button', { name: 'Neuer Artikel' }));
    const dialog = await findDialog('Neuer Artikel');
    await user.type(within(dialog).getByRole('textbox', { name: 'Titel', hidden: true }), 'X');
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen', hidden: true }));

    expect(await within(dialog).findByText('Titel darf nicht leer sein')).toBeInTheDocument();
  });
});
