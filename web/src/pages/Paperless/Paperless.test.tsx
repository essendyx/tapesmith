import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { LocationProbe, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { LabelSource } from '../../api/types';
import PaperlessPage from './index';

const ASN_NEXT = {
  paperless_next: 42,
  local_next: null,
  next: 'ASN00042',
  prefix: 'ASN',
  width: 5,
  hint: 'Vor dem Serieneinsatz einmal testen: ein ASN-Label auf ein Blatt kleben, einscannen und prüfen.',
};

function baseRoutes(overrides: Record<string, (req: { body: unknown; query: URLSearchParams }) => unknown> = {}) {
  return {
    'GET /api/v1/homelab/paperless/asn/next': () => ASN_NEXT,
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    ...overrides,
  };
}

describe('Paperless: ASN-Serien', () => {
  it('zeigt die nächste Nummer und den Scan-Test-Hinweis', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<PaperlessPage />);
    expect(await screen.findByText('ASN00042', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(ASN_NEXT.hint, { exact: false })).toBeInTheDocument();
  });

  it('Reservieren sendet {count: 5} und navigiert zum Serien-Dialog der Vorlage asn', async () => {
    const api = mockApi(
      baseRoutes({
        'POST /api/v1/homelab/paperless/asn/reserve': () => ({
          numbers: ['ASN00042', 'ASN00043', 'ASN00044', 'ASN00045', 'ASN00046'],
          pending_id: 'pend-1',
          template: 'asn',
          hint: ASN_NEXT.hint,
        }),
      }),
    );
    const { user } = renderWithProviders(
      <>
        <PaperlessPage />
        <LocationProbe />
      </>,
    );
    await screen.findByText('ASN00042', { exact: false });

    const countField = screen.getByLabelText('Anzahl');
    await user.clear(countField);
    await user.type(countField, '5');
    await user.click(screen.getByRole('button', { name: 'Reservieren und Serie öffnen' }));

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/homelab/paperless/asn/reserve')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/homelab/paperless/asn/reserve');
    expect(call?.body).toEqual({ count: 5 });

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=asn&import=pend-1'));
  });
});

describe('Paperless: Garantie', () => {
  function warrantyResponse() {
    return {
      warranty: {
        document: { id: 17, title: 'Rechnung Kaffeemaschine', created: '31.01.2026', correspondent: 'MediaMarkt', asn: null, custom: {}, url: 'http://paperless/documents/17/details' },
        kaufdatum: '31.01.2026',
        monate: null,
        ende: '30.06.2029',
        quelle: 'Custom Field Kaufdatum',
        quelle_ende: 'Custom Field Garantie bis',
      },
      label: {
        template: 'garantie-qr',
        values: { geraet: 'Kaffeemaschine', kaufdatum: '31.01.2026', ende: '30.06.2029', link: 'HTTPS://L.EXAMPLE.COM/DOC-17' },
      },
      warnings: [],
    };
  }

  function garantieRoutes() {
    return baseRoutes({
      'GET /api/v1/homelab/paperless/documents': () => ({
        documents: [
          { id: 17, title: 'Rechnung Kaffeemaschine', created: '31.01.2026', correspondent: 'MediaMarkt', asn: null, custom: {}, url: 'http://paperless/documents/17/details' },
        ],
      }),
      'GET /api/v1/homelab/paperless/documents/:id/warranty': () => warrantyResponse(),
    });
  }

  it('Suche sendet die Parameter, Auswahl zeigt das Formular', async () => {
    const api = mockApi(garantieRoutes());
    const { user } = renderWithProviders(<PaperlessPage />);
    await user.click(screen.getByRole('tab', { name: 'Garantie' }));
    await user.type(screen.getByLabelText('Text'), 'Rechnung');
    await user.type(screen.getByLabelText('Händler'), 'Media');
    await user.click(screen.getByRole('button', { name: 'Suchen' }));

    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith('/api/v1/homelab/paperless/documents?'))).toBe(true));
    const call = api.calls.find((c) => c.path.startsWith('/api/v1/homelab/paperless/documents?'));
    const params = new URLSearchParams(call?.path.split('?')[1]);
    expect(params.get('query')).toBe('Rechnung');
    expect(params.get('correspondent')).toBe('Media');

    await user.click(await screen.findByText('Rechnung Kaffeemaschine'));
    expect(await screen.findByText('Garantie-Etikett')).toBeInTheDocument();
  });

  it('Drucken sendet labels/print mit template garantie-qr, link und ende genau wie angezeigt', async () => {
    const api = mockApi({
      ...garantieRoutes(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'Garantie' }),
    });
    const { user } = renderWithProviders(<PaperlessPage />);
    await user.click(screen.getByRole('tab', { name: 'Garantie' }));
    await user.click(screen.getByRole('button', { name: 'Suchen' }));
    await user.click(await screen.findByText('Rechnung Kaffeemaschine'));

    expect(await screen.findByText('30.06.2029', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Custom Field Garantie bis', { exact: false })).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).not.toBeDisabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const printCall = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const source = (printCall?.body as { source: LabelSource }).source;
    expect(source).toMatchObject({
      kind: 'template',
      template: 'garantie-qr',
      values: { ende: '30.06.2029', link: 'HTTPS://L.EXAMPLE.COM/DOC-17' },
    });
  });
});
