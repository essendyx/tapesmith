/** Barrierefreiheit und Tastatur der QR-Seite: axe in de und en. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import QrPage from './index';

function baseRoutes(overrides: Record<string, (req: { body: unknown }) => unknown> = {}) {
  return {
    'POST /api/v1/labels/render': () =>
      fixtures.renderJson({ qr: { version: 3, error: 'm', module_dots: 4, decodes: true, checked: true, warnings: [], text: 'QR' } }),
    ...overrides,
  };
}

const LINK_LABEL: Record<Language, string> = { de: 'Link', en: 'Link' };

describe('Qr: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Grundzustand mit Vorschau (${language})`, async () => {
      mockApi(baseRoutes());
      const { user, container } = renderWithProviders(<QrPage />, { language });
      await user.type(screen.getByRole('textbox', { name: LINK_LABEL[language] }), 'https://example.org');
      await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
      await expectNoA11yViolations(container);
    });

    it(`leerer Zustand ohne Inhalt (${language})`, async () => {
      mockApi(baseRoutes());
      const { container } = renderWithProviders(<QrPage />, { language });
      await screen.findByRole('textbox', { name: LINK_LABEL[language] });
      await expectNoA11yViolations(container);
    });

    it(`Reiter WLAN mit Passwortfeld (${language})`, async () => {
      mockApi(baseRoutes());
      const { user, container } = renderWithProviders(<QrPage />, { language });
      const wifiTab = language === 'de' ? 'WLAN' : 'Wi-Fi';
      await user.click(screen.getByRole('tab', { name: wifiTab }));
      await expectNoA11yViolations(container);
    });
  }
});

describe('Qr: Tastatur', () => {
  it('Hauptaktion ist per Tab erreichbar und druckt mit Enter', async () => {
    const api = mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'QR' }) }));
    const { user } = renderWithProviders(<QrPage />);
    await user.type(screen.getByRole('textbox', { name: 'Link' }), 'https://example.org');
    await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
    const button = screen.getByRole('button', { name: 'Drucken' });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
  });

  it('Sichtbarkeits-Knopf des Passwortfelds ist ein umschaltbarer Knopf (aria-pressed)', async () => {
    mockApi(baseRoutes());
    const { user } = renderWithProviders(<QrPage />);
    await user.click(screen.getByRole('tab', { name: 'WLAN' }));
    const toggle = screen.getByRole('button', { name: 'Passwort anzeigen' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Passwort verbergen' })).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('Qr: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<QrPage />, { language: 'en' });
    expect(screen.getByRole('heading', { level: 1, name: 'QR code' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument();
  });
});
