import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, mockApi, renderWithProviders, type MockHandler } from '../../test/utils';
import KabelPage from './index';
import type { IdsRequest, NetboxPreviewJson, NetboxTableJson } from './types';

function previewResponse(): NetboxPreviewJson {
  return {
    headers: ['ID', 'Label', 'Side A', 'Termination A', 'Side B', 'Termination B', 'Type'],
    mapping: { kabel_id: 'Label', quelle: 'Side A', ziel: 'Side B', kabeltyp: 'Type' },
    rows: [
      { kabel_id: 'K-100', quelle: 'SW1', ziel: 'pmx10', kabeltyp: 'Cat6', farbe: '', laenge: '', neu: false },
      { kabel_id: 'K-101', quelle: 'SW2', ziel: 'pmx11', kabeltyp: 'Cat6a', farbe: '', laenge: '', neu: false },
    ],
    duplicates: ['K-100'],
    warnings: [],
    preview_only: true,
  };
}

function tableResponse(): NetboxTableJson {
  return { pending_id: 'abc123', template: 'kabelfahne', count: 2, new_ids: [], duplicates: [], warnings: [] };
}

function routes(extra: Record<string, MockHandler> = {}): Record<string, MockHandler> {
  return {
    'GET /api/v1/homelab/kabel/register': () => ({ entries: [] }),
    ...extra,
  };
}

describe('Kabel', () => {
  it('Datei-Upload sendet csv_b64, zeigt Zeilen und Duplikat-Warnung; „Als Serie öffnen” navigiert', async () => {
    let netboxBody: unknown = null;
    let tableBody: unknown = null;
    mockApi(
      routes({
        'POST /api/v1/homelab/kabel/netbox': ({ body }) => {
          netboxBody = body;
          return previewResponse();
        },
        'POST /api/v1/homelab/kabel/table': ({ body }) => {
          tableBody = body;
          return tableResponse();
        },
      }),
    );
    const { user } = renderWithProviders(
      <>
        <KabelPage />
        <LocationProbe />
      </>,
      { route: '/homelab/kabel' },
    );

    const fileInput = (await screen.findByLabelText('NetBox-CSV hochladen')) as HTMLInputElement;
    const file = new File(['ID,Label,Side A\n1,K-100,SW1'], 'cables-export.csv', { type: 'text/csv' });
    await user.upload(fileInput, file);

    await waitFor(() => expect(netboxBody).not.toBeNull());
    expect((netboxBody as { csv_b64: string }).csv_b64.length).toBeGreaterThan(0);

    expect(await screen.findByText('SW1')).toBeInTheDocument();
    const dupBar = await screen.findByTestId('netbox-duplicates');
    expect(within(dupBar).getByText(/K-100/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Als Serie öffnen' }));

    await waitFor(() => expect(tableBody).not.toBeNull());
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=kabelfahne&import=abc123'),
    );
  });

  it('ID-Schema sendet {mode: "schema", ranges: [...]} und zeigt die erzeugten IDs', async () => {
    let idsBody: IdsRequest | null = null;
    mockApi(
      routes({
        'POST /api/v1/homelab/kabel/ids': ({ body }) => {
          idsBody = body as IdsRequest;
          return { ids: ['R1.U01:P01', 'R1.U01:P02'], duplicates: [], pending_id: null };
        },
      }),
    );
    const { user } = renderWithProviders(<KabelPage />, { route: '/homelab/kabel' });

    await user.click(await screen.findByRole('tab', { name: 'ID-Schema' }));

    await waitFor(() => expect(idsBody).not.toBeNull());
    expect(idsBody).toMatchObject({
      mode: 'schema',
      ranges: [{ rack: 'R1', units: '1', ports: '1-24' }],
    });

    const list = await screen.findByTestId('ids-list');
    expect(within(list).getByText('R1.U01:P01')).toBeInTheDocument();
    expect(within(list).getByText('R1.U01:P02')).toBeInTheDocument();
  });
});
