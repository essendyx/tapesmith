import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { fixtures, LocationProbe, MockResponse, mockApi, mockNarrowScreen, renderWithProviders } from '../../test/utils';
import type { BatchPlanJson, DiskJson, DriveJson, SshHostJson } from '../../api/types';
import DatentraegerPage from '.';

const drive: DriveJson = {
  root: 'E:\\',
  label: 'KINGSTON',
  size_bytes: 64_000_000_000,
  free_bytes: 32_000_000_000,
  filesystem: 'exFAT',
  bus: 'usb',
  removable: true,
  size_text: '64 GB',
  suggestion: ['USB-Stick', 'Kingston 64 GB'],
};

const host: SshHostJson = { name: 'pmx10', host: '192.0.2.60', user: 'root', port: 22, key: '%USERPROFILE%\\.ssh\\id_ed25519_homelab' };

const disk1: DiskJson = { host: 'pmx10', device: 'sda', model: 'WDC WD40', serial: 'SN-1', size: '3.6T', tran: 'sata', wwn: '', by_id: 'ata-WDC-1', pool: 'tank', vdev: 'mirror-0' };
const disk2: DiskJson = { host: 'pmx10', device: 'sdb', model: 'WDC WD40', serial: 'SN-2', size: '3.6T', tran: 'sata', wwn: '', by_id: 'ata-WDC-2', pool: 'tank', vdev: 'mirror-0' };

describe('DatentraegerPage', () => {
  it('Laufwerk-Karte zeigt „64 GB" und Vorschlag; „Drucken" sendet labels/print mit Text-Quelle und den Vorschlagszeilen', async () => {
    const api = mockApi({
      'GET /api/v1/drives': () => ({ drives: [drive] }),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ title: 'USB-Stick' }),
    });
    const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger' });
    expect(await screen.findByText((text) => text.includes('64 GB · exFAT'))).toBeInTheDocument();
    expect(screen.getByText('USB-Stick')).toBeInTheDocument();
    expect(screen.getByText('Kingston 64 GB')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { source: { kind: string; lines: string[] } };
    expect(body.source).toEqual({ kind: 'text', lines: ['USB-Stick', 'Kingston 64 GB'] });
  });

  it('Laufwerke: fehlschlagender initialer Request zeigt eine Meldung statt leerer Seite', async () => {
    mockApi({
      'GET /api/v1/drives': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Laufwerke nicht lesbar', hint: 'USB-Controller pruefen', exit_code: 1, details: null } }),
    });
    renderWithProviders(<DatentraegerPage />, { route: '/datentraeger' });
    expect(await screen.findByText('Laufwerke nicht lesbar')).toBeInTheDocument();
    expect(screen.getByText('USB-Controller pruefen')).toBeInTheDocument();
    // Weder Kartenliste noch der irreführende Leer-Hinweis erscheinen
    expect(screen.queryByText('Kein USB-Stick oder keine SD-Karte gefunden')).not.toBeInTheDocument();
  });

  it('„Im Schnelldruck anpassen" navigiert zu /schnelldruck?text=…', async () => {
    mockApi({ 'GET /api/v1/drives': () => ({ drives: [drive] }) });
    const { user } = renderWithProviders(
      <>
        <DatentraegerPage />
        <LocationProbe />
      </>,
      { route: '/datentraeger' },
    );
    await screen.findByText((text) => text.includes('64 GB · exFAT'));
    await user.click(screen.getByRole('button', { name: 'Im Schnelldruck anpassen' }));
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(`/schnelldruck?text=${encodeURIComponent('USB-Stick\nKingston 64 GB')}`),
    );
  });

  it('?tab=ssh zeigt SSH', async () => {
    mockApi({ 'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }) });
    renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
    expect(await screen.findByText('pmx10')).toBeInTheDocument();
  });

  it('Scan-Fehler (502 mit kind: "SSH") zeigt Meldung und Hinweis', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/ssh/scan': () =>
        new MockResponse(502, { error: { kind: 'SSH', message: 'Host-Schlüssel nicht bekannt', hint: 'Host-Schlüssel bestätigen und erneut versuchen', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
    await screen.findByText('pmx10');
    await user.click(screen.getByRole('button', { name: 'Scannen' }));
    expect(await screen.findByText('Host-Schlüssel nicht bekannt')).toBeInTheDocument();
    expect(screen.getByText('Host-Schlüssel bestätigen und erneut versuchen')).toBeInTheDocument();
  });

  it('Auswahl von 2 Platten mit Slot "1" und "2" sendet /ssh/series mit slots; Druck sendet /ssh/series/print; Plan mit errors deaktiviert „Drucken"', async () => {
    const plan: BatchPlanJson = { count: 2, summary: '2 Platten', mapping: {}, headers: [], warnings: [], errors: [], previews: [{ index: 0, title: 'sda', design_png: fixtures.pngB64 }] };
    const api = mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1, disk2] }),
      'POST /api/v1/ssh/series': () => plan,
      'POST /api/v1/ssh/series/print': () => fixtures.outcomeJson({ title: 'Serie' }),
    });
    const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
    await screen.findByText('pmx10');
    await user.click(screen.getByRole('button', { name: 'Scannen' }));
    await screen.findByText('sda');

    const slotSda = screen.getByLabelText('Slot für sda');
    await user.clear(slotSda);
    await user.type(slotSda, '1');
    const slotSdb = screen.getByLabelText('Slot für sdb');
    await user.clear(slotSdb);
    await user.type(slotSdb, '2');

    // Drucken ist ohne Plan gesperrt
    expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Vorschau' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/ssh/series')).toBe(true));
    const planCall = api.calls.find((c) => c.path === '/api/v1/ssh/series');
    const planBody = planCall?.body as { slots: Record<string, string> };
    expect(planBody.slots).toEqual({ sda: '1', sdb: '2' });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).not.toBeDisabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/ssh/series/print')).toBe(true));
  });

  it('Plan mit errors deaktiviert „Drucken"', async () => {
    const plan: BatchPlanJson = { count: 1, summary: '1 Platte', mapping: {}, headers: [], warnings: [], errors: ['Seriennummer fehlt'], previews: [] };
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1] }),
      'POST /api/v1/ssh/series': () => plan,
    });
    const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
    await screen.findByText('pmx10');
    await user.click(screen.getByRole('button', { name: 'Scannen' }));
    await screen.findByText('sda');
    await user.click(screen.getByRole('button', { name: 'Vorschau' }));
    await screen.findByText('Seriennummer fehlt');
    expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled();
  });
  it('SSH: fehlschlagender Hosts-Load (500) zeigt eine Meldung statt leerem Dropdown', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Einstellungen nicht lesbar', hint: 'Konfigurationsdatei pruefen', exit_code: 1, details: null } }),
    });
    renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
    expect(await screen.findByText('Einstellungen nicht lesbar')).toBeInTheDocument();
    expect(screen.getByText('Konfigurationsdatei pruefen')).toBeInTheDocument();
  });

  it('SSH: fehlschlagendes /ssh/series (422) zeigt eine Meldung', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1] }),
      'POST /api/v1/ssh/series': () =>
        new MockResponse(422, { error: { kind: 'Validierung', message: 'Slot ungueltig', hint: 'Nur Ziffern erlaubt', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
    await screen.findByText('pmx10');
    await user.click(screen.getByRole('button', { name: 'Scannen' }));
    await screen.findByText('sda');
    await user.click(screen.getByRole('button', { name: 'Vorschau' }));
    expect(await screen.findByText('Slot ungueltig')).toBeInTheDocument();
    expect(screen.getByText('Nur Ziffern erlaubt')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Vorschau' })).not.toBeDisabled();
  });
  describe('jede Änderung verwirft die Vorschau', () => {
    const okPlan: BatchPlanJson = { count: 2, summary: '2 Platten geplant', mapping: {}, headers: [], warnings: [], errors: [], previews: [] };

    async function withPreview() {
      const api = mockApi({
        'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
        'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1, disk2] }),
        'POST /api/v1/ssh/series': () => okPlan,
      });
      const r = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
      await screen.findByText('pmx10');
      await r.user.click(screen.getByRole('button', { name: 'Scannen' }));
      await screen.findByText('sda');
      await r.user.click(screen.getByRole('button', { name: 'Vorschau' }));
      await screen.findByText('2 Platten geplant');
      await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
      return { ...r, api };
    }

    async function expectInvalidated(user: Awaited<ReturnType<typeof withPreview>>['user']) {
      expect(screen.queryByText('2 Platten geplant')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled();
      await user.click(screen.getByRole('button', { name: 'Vorschau' }));
      await screen.findByText('2 Platten geplant');
      await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    }

    it('Auswahl', async () => {
      const { user } = await withPreview();
      await user.click(screen.getByLabelText('sdb auswählen'));
      await expectInvalidated(user);
    });

    it('Slot', async () => {
      const { user } = await withPreview();
      await user.type(screen.getByLabelText('Slot für sda'), '9');
      await expectInvalidated(user);
    });

    it('Kette', async () => {
      const { user } = await withPreview();
      await user.click(screen.getByRole('switch', { name: 'Als Kette' }));
      await expectInvalidated(user);
    });

    it('Schnittmarken', async () => {
      const { user } = await withPreview();
      await user.click(screen.getByRole('switch', { name: 'Schnittmarken' }));
      await expectInvalidated(user);
    });

    it('eine während der Änderung laufende Vorschau wird verworfen', async () => {
      let release: (v: BatchPlanJson) => void = () => undefined;
      mockApi({
        'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
        'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1, disk2] }),
        'POST /api/v1/ssh/series': () =>
          new Promise<BatchPlanJson>((resolve) => {
            release = resolve;
          }),
      });
      const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
      await screen.findByText('pmx10');
      await user.click(screen.getByRole('button', { name: 'Scannen' }));
      await screen.findByText('sda');
      await user.click(screen.getByRole('button', { name: 'Vorschau' }));
      await user.type(screen.getByLabelText('Slot für sda'), '9');
      release(okPlan);
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(screen.queryByText('2 Platten geplant')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled();
    });
  });

  it('SSH bei schmaler Breite als Karten statt Tabelle, Eingaben bleiben bedienbar', async () => {
    const restore = mockNarrowScreen(true);
    try {
      mockApi({
        'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
        'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1, disk2] }),
      });
      const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
      await screen.findByText('pmx10');
      await user.click(screen.getByRole('button', { name: 'Scannen' }));
      const list = await screen.findByRole('list', { name: 'Gefundene Platten' });
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      const cards = within(list).getAllByRole('listitem');
      expect(cards).toHaveLength(2);
      expect(within(cards[0]!).getByText('SN-1')).toBeInTheDocument();
      expect(within(cards[0]!).getByLabelText('Slot für sda')).toBeInTheDocument();
      expect(within(cards[1]!).getByLabelText('sdb auswählen')).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it('SSH bei breitem Bildschirm Tabelle in eigenem, seitlich scrollbarem Container', async () => {
    const restore = mockNarrowScreen(false);
    try {
      mockApi({
        'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
        'POST /api/v1/ssh/scan': () => ({ host: 'pmx10', disks: [disk1] }),
      });
      const { user } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh' });
      await screen.findByText('pmx10');
      await user.click(screen.getByRole('button', { name: 'Scannen' }));
      const table = await screen.findByRole('table', { name: 'Gefundene Platten' });
      expect(getComputedStyle(table.parentElement as HTMLElement).overflowX).toBe('auto');
    } finally {
      restore();
    }
  });
});
