import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { CodescanResultJson } from './types';
import SnScanPage from '.';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    prepareImage: vi.fn(async () => 'ZmFrZS1iaWxk'),
  };
});

function file(): File {
  return new File(['fake-bild'], 'aufkleber.png', { type: 'image/png' });
}

const RESULT: CodescanResultJson = {
  width: 800,
  height: 600,
  hits: [
    { text: 'S/N ABC123456', format: 'Code128', position: [10, 10, 100, 40] },
    { text: '4006381333931', format: 'EAN13', position: [10, 60, 90, 30] },
  ],
  candidates: [
    { serial: 'ABC123456', score: 90, reason: 'Präfix S/N, Code128', text: 'S/N ABC123456', format: 'Code128' },
    { serial: '4006381333931', score: -50, reason: 'EAN: eher Artikelnummer', text: '4006381333931', format: 'EAN13' },
  ],
  best: 'ABC123456',
  shortened: '123456',
};

async function uploadPhoto(user: ReturnType<typeof renderWithProviders>['user']): Promise<void> {
  const input = screen.getByLabelText('Foto des Aufklebers auswählen', { selector: 'input' });
  await user.upload(input, file());
}

describe('SnScanPage', () => {
  it('Upload sendet image_b64, zeigt Kandidaten und wählt den besten vor', async () => {
    const api = mockApi({
      'POST /api/v1/homelab/codescan': () => RESULT,
    });
    const { user } = renderWithProviders(<SnScanPage />, { route: '/homelab/sn-scan' });

    await uploadPhoto(user);

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/homelab/codescan')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/homelab/codescan');
    expect((call?.body as { image_b64: string }).image_b64).toBe('ZmFrZS1iaWxk');

    expect(await screen.findByText('ABC123456')).toBeInTheDocument();
    expect(screen.getByText('4006381333931')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /ABC123456/ })).toBeChecked();
    expect(screen.getByText('Auf dem Label: SN 123456')).toBeInTheDocument();
  });

  it('„In Datenträger-Label übernehmen" navigiert zu /vorlagen mit sn/host/slot', async () => {
    mockApi({ 'POST /api/v1/homelab/codescan': () => RESULT });
    const { user } = renderWithProviders(
      <>
        <SnScanPage />
        <LocationProbe />
      </>,
      { route: '/homelab/sn-scan' },
    );

    await uploadPhoto(user);
    await screen.findByText('ABC123456');

    await user.type(screen.getByLabelText('Host (optional)'), 'pmx10');
    await user.type(screen.getByLabelText('Slot (optional)'), 'SSD-1');
    await user.click(screen.getByRole('button', { name: 'In Datenträger-Label übernehmen' }));

    const expectedWerte = encodeURIComponent(JSON.stringify({ sn: 'ABC123456', host: 'pmx10', slot: 'SSD-1' }));
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(`/vorlagen?vorlage=datentraeger&werte=${expectedWerte}`),
    );
  });

  it('keine erkannten Codes zeigt Tipps statt Kandidatenliste', async () => {
    mockApi({
      'POST /api/v1/homelab/codescan': () => ({
        width: 400,
        height: 300,
        hits: [],
        candidates: [],
        best: null,
        shortened: null,
      }),
    });
    const { user } = renderWithProviders(<SnScanPage />, { route: '/homelab/sn-scan' });

    await uploadPhoto(user);

    expect(await screen.findByText('Keine Codes gefunden')).toBeInTheDocument();
    expect(screen.getByText(/Blitz ausschalten/)).toBeInTheDocument();
  });

  it('Fehler 422 der Route zeigt Meldung', async () => {
    mockApi({
      'POST /api/v1/homelab/codescan': () =>
        new MockResponse(422, {
          error: { kind: 'ValueError', message: 'Datei ist kein lesbares Bild', hint: '', exit_code: 1, details: null },
        }),
    });
    const { user } = renderWithProviders(<SnScanPage />, { route: '/homelab/sn-scan' });

    await uploadPhoto(user);

    expect(await screen.findByText('Datei ist kein lesbares Bild')).toBeInTheDocument();
  });
});
