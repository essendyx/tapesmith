import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, findDialog, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { AssetJson, AssetsListResponse } from './types';
import AssetsPage from '.';

const asset1: AssetJson = {
  id: 'HL-0001',
  bezeichnung: 'Patchkabel Cat6 3m',
  kategorie: 'Netzwerk',
  standort: 'Schrank 1',
  seriennummer: '',
  host: '',
  ziel: 'https://x.example/a',
  paperless_doc: null,
  status: 'aktiv',
  notiz: '',
  created: '2026-09-28T09:00:00',
  updated: '2026-09-28T09:00:00',
};

function listResponse(o: Partial<AssetsListResponse> = {}): AssetsListResponse {
  return {
    assets: [asset1],
    range: { prefix: 'HL-', width: 4, next: 'HL-0002', check_digit: false },
    shortlink: true,
    ...o,
  };
}

describe('AssetsPage', () => {
  it('zeigt die Liste und die nächste Nummer', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse() });
    renderWithProviders(<AssetsPage />);

    expect(await screen.findByText('HL-0001')).toBeInTheDocument();
    expect(screen.getByText('Patchkabel Cat6 3m')).toBeInTheDocument();
    expect(screen.getByText(/Nächste Nummer: HL-0002/)).toBeInTheDocument();
  });

  it('zeigt eine Warnung, wenn der Kurz-Link-Dienst nicht eingerichtet ist', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse({ shortlink: false }) });
    renderWithProviders(<AssetsPage />);

    expect(await screen.findByText('Kurz-Link-Dienst nicht eingerichtet')).toBeInTheDocument();
  });

  it('„Neue Assets" sendet POST /homelab/assets mit count und Feldern', async () => {
    const api = mockApi({
      'GET /api/v1/homelab/assets': () => listResponse({ assets: [] }),
      'POST /api/v1/homelab/assets': () => ({ assets: [{ ...asset1, id: 'HL-0002' }, { ...asset1, id: 'HL-0003' }], warnings: [] }),
    });
    const { user } = renderWithProviders(<AssetsPage />);
    await screen.findByText(/Nächste Nummer/);

    await user.click(screen.getByRole('button', { name: 'Neue Assets' }));
    const dialog = await findDialog('Neue Assets');
    const count = within(dialog).getByLabelText(/Anzahl/);
    await user.clear(count);
    await user.type(count, '2');
    await user.type(within(dialog).getByLabelText(/Bezeichnung/), 'Test');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern' }));

    await waitFor(() =>
      expect(api.calls.find((c) => c.path === '/api/v1/homelab/assets' && c.method === 'POST')?.body).toEqual(
        expect.objectContaining({ count: 2, bezeichnung: 'Test' }),
      ),
    );
  });

  it('„Label drucken" lädt /label und druckt über labels/print mit template asset-kurz', async () => {
    const api = mockApi({
      'GET /api/v1/homelab/assets': () => listResponse(),
      'GET /api/v1/homelab/assets/:id/label': () => ({
        template: 'asset-kurz',
        values: { nummer: 'HL-0001', bezeichnung: 'Patchkabel Cat6 3m', link: 'HTTPS://L.EXAMPLE.COM/HL-0001' },
        warnings: [],
      }),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson(),
    });
    const { user } = renderWithProviders(<AssetsPage />);
    await screen.findByText('HL-0001');

    await user.click(screen.getByRole('button', { name: 'Label drucken' }));

    await waitFor(() =>
      expect(api.calls.find((c) => c.path === '/api/v1/labels/print')?.body).toEqual(
        expect.objectContaining({
          source: { kind: 'template', template: 'asset-kurz', values: { nummer: 'HL-0001', bezeichnung: 'Patchkabel Cat6 3m', link: 'HTTPS://L.EXAMPLE.COM/HL-0001' } },
        }),
      ),
    );
  });

  it('„Vault-Notiz anlegen" sendet POST und zeigt den Pfad', async () => {
    const api = mockApi({
      'GET /api/v1/homelab/assets': () => listResponse(),
      'POST /api/v1/homelab/assets/:id/vault-note': () => ({ path: 'Assets/HL-0001' }),
    });
    const { user } = renderWithProviders(<AssetsPage />);
    await screen.findByText('HL-0001');

    await user.click(screen.getByRole('button', { name: 'Vault-Notiz anlegen' }));

    await waitFor(() =>
      expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/homelab/assets/HL-0001/vault-note')).toBe(true),
    );
    expect(await screen.findByText(/Vault-Notiz angelegt: Assets\/HL-0001/)).toBeInTheDocument();
  });

  it('„Als Serie drucken" navigiert zu /vorlagen?vorlage=asset-kurz&import=<id>', async () => {
    mockApi({
      'GET /api/v1/homelab/assets': () => listResponse(),
      'POST /api/v1/homelab/assets/table': () => ({ pending_id: 'p1', template: 'asset-kurz', count: 1, warnings: [] }),
    });
    const { user } = renderWithProviders(
      <>
        <AssetsPage />
        <LocationProbe />
      </>,
    );
    await screen.findByText('HL-0001');

    await user.click(screen.getByLabelText('HL-0001 auswählen'));
    await user.click(screen.getByRole('button', { name: /Als Serie drucken/ }));

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=asset-kurz&import=p1'));
  });
});
