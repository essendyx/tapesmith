/** Einstellungen: Karte Module, Einstellungskarten der Module, Abschnitt „Erweitert“ und Einheiten. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import { MODULES } from '../../modules';
import { baseSettingsRoutes, makeSettings } from './testFixtures';
import { ADVANCED_STORAGE_KEY } from './sectionIds';
import EinstellungenPage from './index';

const HOMELAB = {
  settings: {
    proxmox: { hosts: [], timeout_s: 10 },
    paperless: {
      url: null,
      public_url: null,
      token_ref: 'keyring:tapesmith/paperless',
      token_set: false,
      token_describe: 'Windows-Anmeldeinformationen',
      asn_range: 'asn',
      asn_prefix: 'ASN',
      asn_width: 5,
      warranty_fields: { kaufdatum: 'Kaufdatum', garantie_monate: 'Garantie Monate', garantie_bis: 'Garantie bis' },
      timeout_s: 10,
    },
    plausi: { networks: ['192.0.2.0/24'], dns_check: true },
  },
  path: 'C:/App/homelab.json',
};

afterEach(() => {
  try {
    window.localStorage.removeItem(ADVANCED_STORAGE_KEY);
  } catch {
    // ohne Speicher nichts zu tun
  }
  vi.restoreAllMocks();
});

describe('Karte Module', () => {
  it('ein Schalter je Modul mit Erklärsatz; Einschalten sendet PUT und lädt AppInfo neu', async () => {
    const api = mockApi(
      baseSettingsRoutes({
        'GET /api/v1/homelab/settings': () => HOMELAB,
        'PUT /api/v1/modules/:id': ({ params, body }) => ({
          modules: [],
          enabled: (body as { enabled: boolean }).enabled ? [params.id] : [],
        }),
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen', app: { modules: [] } });
    const card = await waitFor(() => {
      const el = document.getElementById('module');
      if (!el) throw new Error('Karte fehlt');
      return el;
    });
    expect(within(card).getAllByRole('switch')).toHaveLength(MODULES.length);
    expect(within(card).getByText('Behalte den Überblick über Boxen, ihren Inhalt und verliehene Dinge.')).toBeInTheDocument();
    const proxmox = within(card).getByRole('switch', { name: 'Proxmox' });
    expect(proxmox).not.toBeChecked();
    const appCalls = () => api.calls.filter((c) => c.path === '/api/v1/app').length;
    const before = appCalls();
    await user.click(proxmox);
    await waitFor(() => expect(api.calls).toContainEqual({ method: 'PUT', path: '/api/v1/modules/proxmox', body: { enabled: true } }));
    await waitFor(() => expect(appCalls()).toBeGreaterThan(before));
    expect(await screen.findByText('Proxmox eingeschaltet')).toBeInTheDocument();
  });

  it('Einstellungskarten nur für eingeschaltete Module', async () => {
    mockApi(baseSettingsRoutes({ 'GET /api/v1/homelab/settings': () => HOMELAB }));
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen', app: { modules: ['paperless'] } });
    await waitFor(() => expect(document.getElementById('modul-paperless')).not.toBeNull());
    expect(document.getElementById('modul-proxmox')).toBeNull();
    expect(document.getElementById('modul-datentraeger')).toBeNull();
    // Die Sprungliste ist erst ab 1024 px sichtbar, in jsdom also verborgen.
    const nav = document.querySelector('nav[aria-label="Abschnitte"]') as HTMLElement;
    const links = Array.from(nav.querySelectorAll('a')).map((a) => a.textContent);
    expect(links).toContain('Paperless');
    expect(links).not.toContain('Proxmox');
    expect(links).toContain('Module');
  });

  it('Modulkarte im Raster: Einheit im Feld, Platzhalter, Token-Hilfe und Prüfen', async () => {
    const api = mockApi(
      baseSettingsRoutes({
        'GET /api/v1/homelab/settings': () => HOMELAB,
        'GET /api/v1/homelab/check': () => ({
          services: [
            { id: 'paperless', label: 'Paperless', configured: false, token_set: false, detail: '' },
            { id: 'proxmox', label: 'Proxmox', configured: false, token_set: null, detail: '' },
          ],
        }),
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen', app: { modules: ['paperless'] } });
    const card = await waitFor(() => {
      const el = document.getElementById('modul-paperless');
      if (!el) throw new Error('Karte fehlt');
      return el;
    });
    const width = await within(card).findByRole('textbox', { name: 'Stellen' });
    expect(width).toHaveValue('5');
    expect(within(width.closest('.fui-Input') as HTMLElement).getByText('Stellen')).toBeInTheDocument();
    expect(within(card).getByRole('textbox', { name: 'Adresse' })).toHaveAttribute('placeholder', 'Nicht gesetzt');
    expect(within(card).getByText(/Tapesmith speichert es in den Windows-Anmeldeinformationen/)).toBeInTheDocument();
    expect(await within(card).findByText('Nicht gesetzt', { selector: '.fui-Badge' })).toBeInTheDocument();
    expect(within(card).getByLabelText('Token')).toHaveAttribute('type', 'password');
    expect(within(card).queryByDisplayValue(/keyring:|file:/)).toBeNull();
    await user.click(within(card).getByRole('button', { name: 'Prüfen' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/homelab/check')).toBe(true));
    const state = await within(card).findByRole('status');
    await waitFor(() => expect(within(state).getByText('nicht eingerichtet')).toBeInTheDocument());
    expect(within(state).queryByText('Proxmox')).toBeNull();
  });
});

describe('Abschnitt „Erweitert“', () => {
  it('ist zu Beginn eingeklappt, öffnet per Knopf und merkt sich den Zustand je Browser', async () => {
    mockApi(baseSettingsRoutes());
    const first = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const toggle = await screen.findByRole('button', { name: 'Anzeigen' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('erweitert-verbindung')).toBeNull();
    await first.user.click(toggle);
    expect(await screen.findByRole('button', { name: 'Ausblenden' })).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('erweitert-verbindung')).not.toBeNull();
    expect(window.localStorage.getItem(ADVANCED_STORAGE_KEY)).toBe('offen');
    first.unmount();

    mockApi(baseSettingsRoutes());
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    expect(await screen.findByRole('button', { name: 'Ausblenden' })).toBeInTheDocument();
  });

  it('Deep-Link auf eine Karte darin öffnet den Abschnitt', async () => {
    mockApi(baseSettingsRoutes());
    vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {});
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen?abschnitt=erweitert-verbindung' });
    await waitFor(() => expect(document.getElementById('erweitert-verbindung')).not.toBeNull());
    expect(screen.getByRole('button', { name: 'Ausblenden' })).toBeInTheDocument();
  });

  it('frühere Sprungziele: ?abschnitt=ble öffnet den Abschnitt und springt zur Karte', async () => {
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/settings': () =>
          makeSettings({
            sections: [
              {
                id: 'ble',
                title: 'Bluetooth LE (experimentell)',
                fields: [
                  { key: 'ble.address', label: 'BLE-Adresse', type: 'string', value: null, default: null, nullable: true, visibility: 'erweitert' },
                ],
              },
            ],
          }),
      }),
    );
    vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {});
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen?abschnitt=ble' });
    await waitFor(() => expect(document.getElementById('erweitert-ble')).not.toBeNull());
  });

  it('ohne nutzbaren Speicher bleibt die Seite bedienbar (eingeklappt)', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('gesperrt');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('gesperrt');
    });
    mockApi(baseSettingsRoutes());
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const toggle = await screen.findByRole('button', { name: 'Anzeigen' });
    await user.click(toggle);
    expect(await screen.findByRole('button', { name: 'Ausblenden' })).toBeInTheDocument();
  });

  it('Suche findet auch Felder unter „Erweitert“', async () => {
    mockApi(baseSettingsRoutes());
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    await user.type(await screen.findByRole('textbox', { name: 'Einstellung suchen' }), 'Transport');
    await waitFor(() => expect(document.getElementById('erweitert-verbindung')).not.toBeNull());
  });
});

describe('Zahlenfelder mit Einheit', () => {
  it('zeigt die Einheit im Feld, nimmt Komma an und speichert die Zahl', async () => {
    let sent: Record<string, unknown> | null = null;
    const settings = makeSettings({
      sections: [
        {
          id: 'drucken',
          title: 'Drucken',
          fields: [
            {
              key: 'guard.confirm_label_mm',
              label: 'Rückfrage ab Labellänge',
              type: 'float',
              value: 150,
              default: 150,
              nullable: false,
              min: 1,
              unit: 'mm',
              help: 'Längere Etiketten fragen vor dem Druck nach',
              visibility: 'sichtbar',
            },
          ],
        },
      ],
    });
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/settings': () => settings,
        'PATCH /api/v1/settings': ({ body }) => {
          sent = (body as { changes: Record<string, unknown> }).changes;
          return settings;
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const field = await screen.findByRole('spinbutton', { name: 'Rückfrage ab Labellänge' });
    expect(field).toHaveValue('150');
    expect(field).toHaveAccessibleDescription('mm');
    await user.clear(field);
    await user.type(field, '12,5');
    await user.tab();
    const card = document.getElementById('drucken') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(sent).toEqual({ 'guard.confirm_label_mm': 12.5 }));
  });
});
