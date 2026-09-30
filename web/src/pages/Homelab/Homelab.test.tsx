import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import HomelabPage from '.';
import { routeBreadcrumb } from '../../routes';

const CHECK = {
  services: [
    { id: 'paperless', label: 'Paperless', configured: true, token_set: false, detail: 'Token fehlt' },
    { id: 'proxmox', label: 'Proxmox', configured: false, token_set: null, detail: 'Keine Proxmox-Hosts eingetragen' },
    { id: 'obsidian', label: 'Obsidian', configured: true, token_set: null, detail: 'ohne Token (nur LAN)' },
    { id: 'homeassistant', label: 'Home Assistant', configured: true, token_set: true, detail: 'Token vorhanden' },
    { id: 'shortlink', label: 'Kurz-Link-Dienst', configured: false, token_set: false, detail: 'base_url fehlt' },
  ],
};

/** Wie in App.tsx: die Seite hängt unter `/homelab/*`. */
function Mounted(): JSX.Element {
  return (
    <Routes>
      <Route path="/homelab/*" element={<HomelabPage />} />
    </Routes>
  );
}

function tile(title: string): HTMLElement {
  return screen.getByRole('link', { name: title });
}

describe('HomelabPage', () => {
  it('Hub zeigt je eingeschaltetem Integrationsmodul eine Kachel mit Zustand aus /homelab/check', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => CHECK });
    renderWithProviders(<Mounted />, { route: '/homelab' });

    expect(await screen.findByRole('heading', { name: 'Homelab' })).toBeInTheDocument();
    await waitFor(() => expect(within(tile('Paperless')).getByText('Token fehlt')).toBeInTheDocument());
    expect(screen.getAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/homelab/'))).toHaveLength(8);

    expect(within(tile('Proxmox')).getByText('nicht eingerichtet')).toBeInTheDocument();
    expect(within(tile('Obsidian-Vault')).getByText('eingerichtet')).toBeInTheDocument();
    expect(within(tile('Home Assistant')).getByText('eingerichtet')).toBeInTheDocument();
    expect(within(tile('Assets')).getByText('nicht eingerichtet')).toBeInTheDocument();
    for (const title of ['Kabel', 'Kleinanzeigen', 'Seriennummer-Scan']) {
      expect(within(tile(title)).getByText('kein Dienst nötig')).toBeInTheDocument();
    }
    // Einstellungen und Plattentausch sind keine Kacheln mehr (Einstellungen > Module, Seite Datenträger).
    expect(screen.queryByRole('link', { name: 'Einstellungen' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Plattentausch' })).toBeNull();
  });

  it('nur eingeschaltete Module erscheinen, ohne Module ein hilfreicher Leerzustand', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => CHECK });
    renderWithProviders(<Mounted />, { route: '/homelab', app: { modules: ['proxmox', 'inventar'] } });
    expect(await screen.findByRole('link', { name: 'Proxmox' })).toBeInTheDocument();
    expect(screen.getAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/homelab/'))).toHaveLength(1);
  });

  it('ohne Homelab-Modul: Leerzustand mit Weg zu den Modulen', async () => {
    mockApi({});
    const { user } = renderWithProviders(
      <>
        <Mounted />
        <LocationProbe />
      </>,
      { route: '/homelab', app: { modules: [] } },
    );
    expect(await screen.findByRole('heading', { name: 'Noch kein Homelab-Modul eingeschaltet' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Module verwalten' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/einstellungen?abschnitt=module'));
  });

  it('ausgeschaltetes Modul: Unterseite zeigt nur den Hinweis', async () => {
    mockApi({});
    renderWithProviders(<Mounted />, { route: '/homelab/proxmox', app: { modules: [] } });
    expect(await screen.findByRole('heading', { name: 'Modul Proxmox ist ausgeschaltet' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Zu den Modulen' })).toBeInTheDocument();
  });

  it('Modul ohne eingerichteten Dienst: Erklärsatz und Weg zu den Einstellungen statt Fehler', async () => {
    const api = mockApi({ 'GET /api/v1/homelab/check': () => CHECK }, { quiet: true });
    const { user } = renderWithProviders(
      <>
        <Mounted />
        <LocationProbe />
      </>,
      { route: '/homelab/proxmox' },
    );
    expect(await screen.findByRole('heading', { name: 'Proxmox ist noch nicht eingerichtet' })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith('/api/v1/homelab/proxmox'))).toBe(false);
    await user.click(screen.getByRole('button', { name: 'Zu den Einstellungen' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/einstellungen?abschnitt=modul-proxmox'));
  });

  it('frühere Adressen leiten weiter', async () => {
    mockApi({}, { quiet: true });
    renderWithProviders(
      <>
        <Mounted />
        <LocationProbe />
      </>,
      { route: '/homelab/einstellungen' },
    );
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/einstellungen?abschnitt=module'));
  });

  it('Proxmox mit mehreren Hosts: fehlt ein Token, zeigt die Kachel „Token fehlt“', async () => {
    mockApi({
      'GET /api/v1/homelab/check': () => ({
        services: [
          { id: 'proxmox:pmx10', label: 'Proxmox pmx10', configured: true, token_set: true, detail: '' },
          { id: 'proxmox:pmx20', label: 'Proxmox pmx20', configured: true, token_set: false, detail: '' },
        ],
      }),
    });
    renderWithProviders(<Mounted />, { route: '/homelab' });
    await waitFor(() => expect(within(tile('Proxmox')).getByText('Token fehlt')).toBeInTheDocument());
  });

  it('Fehler beim Prüfen zeigt die Meldung, Kacheln bleiben bedienbar', async () => {
    mockApi({
      'GET /api/v1/homelab/check': () =>
        new MockResponse(422, {
          error: { kind: 'ValueError', message: "homelab.json: unbekannter Schlüssel 'x'", hint: 'Datei prüfen', exit_code: 1, details: null },
        }),
    });
    renderWithProviders(<Mounted />, { route: '/homelab' });
    expect(await screen.findByText("homelab.json: unbekannter Schlüssel 'x'")).toBeInTheDocument();
    expect(screen.getByText('Datei prüfen')).toBeInTheDocument();
    expect(tile('Proxmox')).toBeInTheDocument();
  });

  it('Klick auf eine Kachel navigiert zur Unterseite', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => CHECK }, { quiet: true });
    const { user } = renderWithProviders(
      <>
        <Mounted />
        <LocationProbe />
      </>,
      { route: '/homelab' },
    );
    await user.click(await screen.findByRole('link', { name: 'Proxmox' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/homelab/proxmox'));
  });

  it('Route /homelab/sn-scan rendert die SN-Scan-Seite ohne zweiten Pfad über dem Titel (den zeigt die Kopfzeile)', async () => {
    mockApi({}, { quiet: true });
    renderWithProviders(<Mounted />, { route: '/homelab/sn-scan' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Seriennummer-Scan' }, { timeout: 10000 })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Pfad' })).not.toBeInTheDocument();
    expect(routeBreadcrumb('/homelab/sn-scan')).toEqual([
      { label: 'Homelab', path: '/homelab' },
      { label: 'Seriennummer-Scan', path: '/homelab/sn-scan' },
    ]);
  });

  it('unbekannter Unterpfad leitet zur Übersicht zurück', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => CHECK });
    renderWithProviders(
      <>
        <Mounted />
        <LocationProbe />
      </>,
      { route: '/homelab/gibtsnicht' },
    );
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/homelab$/));
    expect(await screen.findByRole('heading', { name: 'Homelab' })).toBeInTheDocument();
  });
});
