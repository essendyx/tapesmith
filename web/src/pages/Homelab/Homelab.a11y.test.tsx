/** Barrierefreiheit und Tastatur der Seite Homelab: axe in de und en, Tastatur, Pfad. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { expectNoA11yViolations } from '../../test/a11y';
import { LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import HomelabPage from '.';

const CHECK = {
  services: [
    { id: 'paperless', label: 'Paperless', configured: true, token_set: false, detail: 'Token fehlt' },
    { id: 'proxmox', label: 'Proxmox', configured: false, token_set: null, detail: 'Keine Proxmox-Hosts eingetragen' },
    { id: 'obsidian', label: 'Obsidian', configured: true, token_set: null, detail: 'ohne Token (nur LAN)' },
    { id: 'homeassistant', label: 'Home Assistant', configured: true, token_set: true, detail: 'Token vorhanden' },
    { id: 'shortlink', label: 'Kurz-Link-Dienst', configured: false, token_set: false, detail: 'base_url fehlt' },
  ],
};

function Mounted(): JSX.Element {
  return (
    <Routes>
      <Route path="/homelab/*" element={<HomelabPage />} />
    </Routes>
  );
}

const HEADING = { de: 'Homelab', en: 'Homelab' } as const;
const PROXMOX_TILE = { de: 'Proxmox', en: 'Proxmox' } as const;

describe.each(['de', 'en'] as Language[])('Seite Homelab: axe (%s)', (language) => {
  it('Grundzustand ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => CHECK });
    const { container } = renderWithProviders(<Mounted />, { route: '/homelab', language });
    await screen.findByRole('heading', { name: HEADING[language] });
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (keine Prüfergebnisse) ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => ({ services: [] }) });
    const { container } = renderWithProviders(<Mounted />, { route: '/homelab', language });
    await screen.findByRole('heading', { name: HEADING[language] });
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand (422) ohne Befund', async () => {
    mockApi({
      'GET /api/v1/homelab/check': () =>
        new MockResponse(422, {
          error: { kind: 'ValueError', message: "homelab.json: unbekannter Schlüssel 'x'", hint: 'Datei prüfen', exit_code: 1, details: null },
        }),
    });
    const { container } = renderWithProviders(<Mounted />, { route: '/homelab', language });
    await screen.findByRole('heading', { name: HEADING[language] });
    await expectNoA11yViolations(container);
  });
});

describe('Seite Homelab: Tastatur', () => {
  it('Kachel „Proxmox“ per Tab erreichbar, Enter navigiert zur Unterseite', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => CHECK }, { quiet: true });
    const { user } = renderWithProviders(
      <>
        <Mounted />
        <LocationProbe />
      </>,
      { route: '/homelab' },
    );
    const tile = await screen.findByRole('link', { name: PROXMOX_TILE.de });
    tile.focus();
    expect(tile).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/homelab/proxmox'));
  });
});
