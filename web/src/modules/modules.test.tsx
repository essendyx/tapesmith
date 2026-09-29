/** Module in der Oberfläche: Seitenleiste, Befehlspalette, Sperre der Modulseiten, Beschreibung aus dem Register. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { fixtures, LocationProbe, mockApi, renderWithProviders } from '../test/utils';
import { HOMELAB_MODULES, MODULE_IDS, moduleForPage, moduleTexts, modulesState } from './index';

function shellApi(modules: string[]) {
  return mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
      'GET /api/v1/app': () => ({ ...fixtures.appInfo, modules }),
      'GET /api/v1/templates': () => ({ templates: [] }),
    },
    { quiet: true },
  );
}

function sidebarRoutes(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Seiten' });
  return within(nav)
    .getAllByRole('button')
    .map((b) => b.getAttribute('data-route'))
    .filter((r): r is string => r !== null);
}

describe('Modulregister (aus Python abgeleitet)', () => {
  it('kennt alle Module mit Texten in beiden Sprachen', () => {
    expect(MODULE_IDS).toEqual([
      'inventar',
      'datentraeger',
      'proxmox',
      'paperless',
      'homeassistant',
      'vault',
      'assets',
      'kabel',
      'kleinanzeigen',
      'snscan',
    ]);
    for (const id of MODULE_IDS) {
      expect(moduleTexts(id, 'de').name).not.toBe('');
      expect(moduleTexts(id, 'en').description).not.toBe('');
    }
  });

  it('ordnet Seiten ihren Modulen zu', () => {
    expect(moduleForPage('/inventar')).toBe('inventar');
    expect(moduleForPage('/homelab/batterien')).toBe('homeassistant');
    expect(moduleForPage('/homelab/sn-scan/x')).toBe('snscan');
    expect(moduleForPage('/schnelldruck')).toBeUndefined();
    expect(HOMELAB_MODULES.map((m) => m.id)).not.toContain('inventar');
  });

  it('Zustand: unbekannt heißt alles aus, bis AppInfo geladen ist', () => {
    expect(modulesState(undefined).loaded).toBe(false);
    expect(modulesState(undefined).isEnabled('inventar')).toBe(false);
    expect(modulesState(['vault']).isEnabled('vault')).toBe(true);
  });
});

describe('Seitenleiste und Befehlspalette', () => {
  it('ohne Module: nur die Kernapp, keine Modulseiten', async () => {
    shellApi([]);
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck', app: { modules: [] } });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await waitFor(() => expect(sidebarRoutes()).toContain('statistik'));
    expect(sidebarRoutes()).toEqual([
      'schnelldruck',
      'editor',
      'galerie',
      'vorlagen',
      'qr',
      'verlauf',
      'warteschlange',
      'statistik',
      'zugriff',
      'einstellungen',
    ]);
  });

  it('eingeschaltetes Integrationsmodul bringt den Eintrag Homelab, Inventar erscheint nur eingeschaltet', async () => {
    shellApi(['proxmox']);
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck', app: { modules: ['proxmox'] } });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await waitFor(() => expect(sidebarRoutes()).toContain('homelab'));
    expect(sidebarRoutes()).not.toContain('inventar');
    expect(sidebarRoutes()).not.toContain('datentraeger');
  });

  it('Befehlspalette: keine Befehle ausgeschalteter Module', async () => {
    shellApi([]);
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck', app: { modules: [] } });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Befehl suchen' });
    await user.type(input, 'inventar');
    const list = screen.getByRole('listbox', { name: 'Befehle' });
    expect(within(list).queryByText(/Inventar/)).toBeNull();
    await user.clear(input);
    await user.type(input, 'ssh');
    expect(within(screen.getByRole('listbox', { name: 'Befehle' })).queryByText(/SSH/)).toBeNull();
  });

  it('Befehlspalette: eingeschaltete Module sind da', async () => {
    shellApi(['inventar']);
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck', app: { modules: ['inventar'] } });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await waitFor(() => expect(sidebarRoutes()).toContain('inventar'));
    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Befehl suchen' });
    await user.type(input, 'inventar');
    await waitFor(() => expect(within(screen.getByRole('listbox', { name: 'Befehle' })).getAllByText(/Inventar/).length).toBeGreaterThan(0));
  });

  it('direkter Aufruf einer ausgeschalteten Modulseite: Hinweis mit Weg zu den Modulen', async () => {
    shellApi([]);
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/inventar', app: { modules: [] } });
    expect(await screen.findByRole('heading', { name: 'Modul Inventar ist ausgeschaltet' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Zu den Modulen' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/einstellungen?abschnitt=module'));
  });
});
