import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { LabelSource, QrSource } from '../../api/types';
import QrPage from './index';

function baseRoutes(overrides: Record<string, (req: { body: unknown }) => unknown> = {}) {
  return {
    'POST /api/v1/labels/render': () =>
      fixtures.renderJson({ qr: { version: 3, error: 'm', module_dots: 4, decodes: true, checked: true, warnings: [], text: 'QR' } }),
    ...overrides,
  };
}

describe('Qr', () => {
  it('Reiter WLAN: Render-Anfrage hat content.type wifi, Passwort erscheint nur im Passwortfeld', async () => {
    const api = mockApi(baseRoutes());
    const { user } = renderWithProviders(<QrPage />);
    await user.click(screen.getByRole('tab', { name: 'WLAN' }));
    await user.type(screen.getByRole('textbox', { name: 'SSID' }), 'Gast');
    const passwordField = screen.getByLabelText('Passwort') as HTMLInputElement;
    await user.type(passwordField, 'geheim123');

    await waitFor(() => {
      const renders = api.calls.filter((c) => c.path === '/api/v1/labels/render');
      expect(renders.length).toBeGreaterThan(0);
      const last = renders.at(-1)?.body as { source: QrSource };
      expect(last.source.content).toMatchObject({ type: 'wifi', ssid: 'Gast', password: 'geheim123' });
    });

    expect(passwordField.value).toBe('geheim123');
    expect(screen.queryByText('geheim123')).toBeNull();
  });

  it('Info-Karte zeigt Version und Selbsttest ok aus render.qr', async () => {
    mockApi(baseRoutes());
    const { user } = renderWithProviders(<QrPage />);
    await user.type(screen.getByRole('textbox', { name: 'Link' }), 'https://example.org');
    expect(await screen.findByText('Version 3')).toBeInTheDocument();
    expect(screen.getByText('Selbsttest ok')).toBeInTheDocument();
  });

  it('Info-Karte zeigt „Nicht rückgelesen“ statt Fehler, wenn der Decoder fehlt', async () => {
    mockApi({
      'POST /api/v1/labels/render': () =>
        fixtures.renderJson({
          qr: { version: 3, error: 'm', module_dots: 4, decodes: false, checked: false, warnings: [], text: 'QR' },
        }),
    });
    const { user } = renderWithProviders(<QrPage />);
    await user.type(screen.getByRole('textbox', { name: 'Link' }), 'https://example.org');
    expect(await screen.findByText('Nicht rückgelesen')).toBeInTheDocument();
    expect(screen.queryByText('Selbsttest fehlgeschlagen')).toBeNull();
  });

  it('?inhalt=https%3A%2F%2Fexample.org waehlt den Reiter URL', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<QrPage />, { route: '/qr?inhalt=https%3A%2F%2Fexample.org' });
    const urlTab = await screen.findByRole('tab', { name: 'URL / Link', selected: true });
    expect(urlTab).toBeInTheDocument();
    const link = screen.getByRole('textbox', { name: 'Link' }) as HTMLInputElement;
    await waitFor(() => expect(link.value).toBe('https://example.org'));
  });

  it('?inhalt=Hallo waehlt den Reiter Text', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<QrPage />, { route: '/qr?inhalt=Hallo' });
    await screen.findByRole('tab', { name: 'Text', selected: true });
    const textField = screen.getByRole('textbox', { name: 'Text' }) as HTMLInputElement;
    await waitFor(() => expect(textField.value).toBe('Hallo'));
  });

  it('Drucken sendet die QR-Quelle', async () => {
    const api = mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'QR' }) }));
    const { user } = renderWithProviders(<QrPage />);
    await user.type(screen.getByRole('textbox', { name: 'Link' }), 'https://example.org');
    await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const printCall = api.calls.find((c) => c.path === '/api/v1/labels/print');
    expect((printCall?.body as { source: LabelSource }).source).toMatchObject({ kind: 'qr', content: { type: 'url', url: 'https://example.org' } });
  });
});
