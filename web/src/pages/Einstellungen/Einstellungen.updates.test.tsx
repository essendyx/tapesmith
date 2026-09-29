/**
 * Einstellungsseite: UpdateCard/SupportCard eingebunden, Deep-Link `?abschnitt=`,
 * Sprache/Farbschema wirken sofort, Ungespeichert-Register.
 */
import { describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { qk } from '../../api/core';
import { fixtures, mockApi, renderWithProviders } from '../../test/utils';
import { baseSettingsRoutes, makeSettings, makeUpdateStatus } from './testFixtures';
import type { SettingsJson } from '../../api/types';
import EinstellungenPage from './index';

describe('/einstellungen: Updates und Problem melden', () => {
  it('UpdateCard ist unter Section id="updates" eingebunden, SectionNav enthält „Updates"', async () => {
    mockApi(baseSettingsRoutes());
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    await waitFor(() => expect(document.getElementById('updates')).not.toBeNull());
    expect(document.querySelector('a[href="#updates"]')).not.toBeNull();
  });

  it('SupportCard ist eingebunden, „Problem melden" lädt POST /support/report', async () => {
    const originalCreate = URL.createObjectURL;
    URL.createObjectURL = () => 'blob:mock';
    try {
      const api = mockApi(
        baseSettingsRoutes({
          'POST /api/v1/support/report': () => new Response('PK', { status: 200, headers: { 'Content-Type': 'application/zip' } }),
        }),
      );
      const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
      await waitFor(() => expect(document.getElementById('support')).not.toBeNull());
      await user.click(screen.getByRole('button', { name: 'Problem melden' }));
      await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/support/report' && c.method === 'POST')).toBe(true));
    } finally {
      URL.createObjectURL = originalCreate;
    }
  });

  it('Deep-Link ?abschnitt=updates scrollt zur Updates-Karte und fokussiert ihre Überschrift', async () => {
    mockApi(baseSettingsRoutes());
    const spy = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {});
    try {
      renderWithProviders(<EinstellungenPage />, { route: '/einstellungen?abschnitt=updates' });
      await waitFor(() => expect(document.getElementById('updates')).not.toBeNull());
      await waitFor(() => {
        const heading = document.getElementById('updates')?.querySelector('h2');
        expect(document.activeElement).toBe(heading);
      });
    } finally {
      spy.mockRestore();
    }
  });

  it('Deep-Link hält die Karte oben, solange darüber Karten nachladen, bis der Nutzer eingreift', async () => {
    mockApi(baseSettingsRoutes());
    const spy = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {});
    try {
      renderWithProviders(<EinstellungenPage />, { route: '/einstellungen?abschnitt=updates' });
      await waitFor(() => expect(document.activeElement).toBe(document.getElementById('updates')?.querySelector('h2')));
      const before = spy.mock.calls.length;
      // Nachladende Karte darüber: die Seite wächst, der Abschnitt wird erneut ausgerichtet.
      await act(async () => {
        document.body.appendChild(document.createElement('div'));
      });
      await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThan(before));
      // Nutzer scrollt selbst: danach kein Nachführen mehr.
      window.dispatchEvent(new Event('wheel'));
      const afterUser = spy.mock.calls.length;
      await act(async () => {
        document.body.appendChild(document.createElement('div'));
      });
      await new Promise((r) => setTimeout(r, 20));
      expect(spy.mock.calls.length).toBe(afterUser);
    } finally {
      spy.mockRestore();
    }
  });

  it('Deep-Link fokussiert nur einmal: neu geladene Einstellungen ziehen den Fokus nicht zurück', async () => {
    let loads = 0;
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/settings': () => {
          loads += 1;
          return makeSettings({ config_path: `C:/Users/test/AppData/Roaming/Tapesmith/config-${loads}.json` });
        },
      }),
    );
    const spy = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {});
    try {
      const { queryClient } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen?abschnitt=updates' });
      await waitFor(() => expect(document.activeElement).toBe(document.getElementById('updates')?.querySelector('h2')));
      const toggle = await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' });
      toggle.focus();
      expect(document.activeElement).toBe(toggle);
      await act(async () => {
        await queryClient.invalidateQueries({ queryKey: qk.settings });
      });
      await waitFor(() => expect(loads).toBeGreaterThanOrEqual(2));
      await waitFor(() => expect(screen.getByText(/config-2\.json/)).toBeInTheDocument());
      expect(document.activeElement).toBe(toggle);
    } finally {
      spy.mockRestore();
    }
  });

  it('Sprache: PATCH app.language wechselt AppInfo, Seitenüberschrift wird sofort Englisch', async () => {
    let language: 'de' | 'en' = 'de';
    const withLanguage = (): SettingsJson => ({
      ...makeSettings(),
      sections: [
        ...makeSettings().sections,
        {
          id: 'oberflaeche',
          title: 'Oberfläche',
          fields: [
            {
              key: 'app.language',
              label: 'Sprache',
              type: 'choice',
              value: language,
              default: 'auto',
              nullable: false,
              choices: [
                { value: 'auto', label: 'wie Windows' },
                { value: 'de', label: 'Deutsch' },
                { value: 'en', label: 'English' },
              ],
            },
          ],
        },
      ],
    });
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/settings': () => withLanguage(),
        'GET /api/v1/app': () => ({ ...fixtures.appInfo, language }),
        'PATCH /api/v1/settings': ({ body }) => {
          const changes = (body as { changes: Record<string, unknown> }).changes;
          if (typeof changes['app.language'] === 'string') language = changes['app.language'] as 'de' | 'en';
          return withLanguage();
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Einstellungen' })).toBeInTheDocument();

    const select = await screen.findByLabelText('Sprache');
    await user.selectOptions(select, 'en');
    const saveButtons = screen.getAllByRole('button', { name: 'Speichern' });
    await user.click(saveButtons[saveButtons.length - 1] as HTMLElement);

    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Settings'));
  });

  it('Ungespeichert-Register: Änderung ohne Speichern zählt als 1', async () => {
    mockApi(baseSettingsRoutes());
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const toggle = await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' });
    expect(window.p12UnsavedCount?.()).toBe(0);
    await user.click(toggle);
    await waitFor(() => expect(window.p12UnsavedCount?.()).toBe(1));
  });

  it('Editierbare Update-Felder (Quelle, Kanal, …) erscheinen als eigene Karte neben der UpdateCard', async () => {
    mockApi(baseSettingsRoutes());
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    await waitFor(() => expect(document.getElementById('updates-felder')).not.toBeNull());
    expect(document.getElementById('updates')).not.toBeNull();
    expect(document.getElementById('updates')).not.toBe(document.getElementById('updates-felder'));
  });

  it('kein doppeltes DOM-id="updates", "druckdienst" oder "support"', async () => {
    mockApi(baseSettingsRoutes());
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    await waitFor(() => expect(document.getElementById('updates')).not.toBeNull());
    await waitFor(() => expect(document.getElementById('druckdienst')).not.toBeNull());
    expect(document.querySelectorAll('#updates').length).toBe(1);
    expect(document.querySelectorAll('#druckdienst').length).toBe(1);
    // Die Angaben zum Druckdienst stehen in „Hilfe und Diagnose“.
    expect(document.querySelectorAll('#support').length).toBe(1);
    expect(document.querySelectorAll('#druckdienst-status').length).toBe(0);
  });

  it('UpdateCard zeigt den ruhigen Standardzustand aus makeUpdateStatus()', async () => {
    mockApi(baseSettingsRoutes({ 'GET /api/v1/update/status': () => makeUpdateStatus({ current: '0.3.0' }) }));
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    expect(await screen.findByText('Installierte Version: 0.3.0')).toBeInTheDocument();
  });
});
