import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, MockResponse, mockApi, renderWithProviders, type MockHandler } from '../../test/utils';
import ProxmoxPage from './index';
import type { GuestsJson, PveHostsJson } from './types';

const HOSTS: PveHostsJson = {
  hosts: [
    {
      name: 'pmx10',
      url: 'https://192.0.2.60:8006',
      verify_tls: false,
      token_set: true,
      token_describe: 'Datei C:\\Tokens\\.proxmox_tapesmith_token',
    },
  ],
};

const GUESTS: GuestsJson = {
  host: 'pmx10',
  nodes: [{ host: 'pmx10', node: 'pmx10', status: 'online', ip: '192.0.2.60' }],
  guests: [
    {
      host: 'pmx10', node: 'pmx10', vmid: 102, kind: 'lxc', name: 'frigate', status: 'running', tags: ['gpu'],
      ips: ['192.0.2.47'], ip_note: '', passthrough: ['dev0: /dev/nvidia0'], ip_kurz: '.47',
    },
    {
      host: 'pmx10', node: 'pmx10', vmid: 111, kind: 'qemu', name: 'webapp1', status: 'running', tags: ['ai', 'gpu'],
      ips: ['192.0.2.39'], ip_note: '', passthrough: ['hostpci0: 0000:01:00.0,pcie=1'], ip_kurz: '.39',
    },
    {
      host: 'pmx10', node: 'pmx10', vmid: 120, kind: 'qemu', name: 'win11-test', status: 'stopped', tags: [],
      ips: [], ip_note: 'IP unbekannt: gestoppt', passthrough: [], ip_kurz: '',
    },
  ],
  warnings: ['TLS-Zertifikat von pmx10 wird nicht geprüft'],
};

function routes(extra: Record<string, MockHandler> = {}): Record<string, MockHandler> {
  return {
    'GET /api/v1/homelab/proxmox/hosts': () => HOSTS,
    'POST /api/v1/homelab/proxmox/guests': () => GUESTS,
    ...extra,
  };
}

function renderPage() {
  return renderWithProviders(
    <>
      <ProxmoxPage />
      <LocationProbe />
    </>,
    { route: '/homelab/proxmox' },
  );
}

describe('Proxmox', () => {
  it('Laden zeigt Gäste mit IP und „IP unbekannt“', async () => {
    const api = mockApi(routes());
    const { user } = renderPage();
    const load = await screen.findByRole('button', { name: 'Laden' });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(load);

    const table = await screen.findByRole('table', { name: 'Gäste' });
    expect(within(table).getByText('webapp1')).toBeInTheDocument();
    expect(within(table).getByText('192.0.2.39')).toBeInTheDocument();
    expect(within(table).getByText('IP unbekannt: gestoppt')).toBeInTheDocument();
    expect(within(table).getByText('hostpci0: 0000:01:00.0,pcie=1')).toBeInTheDocument();
    expect(screen.getByText('TLS-Zertifikat von pmx10 wird nicht geprüft')).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === '/api/v1/homelab/proxmox/guests')?.body).toEqual({ host: 'pmx10' });
  });

  it('Filter „nur laufende“ sendet status running', async () => {
    const api = mockApi(routes());
    const { user } = renderPage();
    const load = await screen.findByRole('button', { name: 'Laden' });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(screen.getByRole('switch', { name: 'nur laufende' }));
    await user.type(screen.getByRole('textbox', { name: 'VMIDs' }), '100-120');
    await user.click(load);
    await screen.findByRole('table', { name: 'Gäste' });
    expect(api.calls.find((c) => c.path === '/api/v1/homelab/proxmox/guests')?.body).toEqual({
      host: 'pmx10',
      status: 'running',
      ids: '100-120',
    });
  });

  it('zwei Gäste auswählen und als Serie drucken navigiert zum Serien-Dialog', async () => {
    let sent: unknown = null;
    mockApi(
      routes({
        'POST /api/v1/homelab/proxmox/table': ({ body }) => {
          sent = body;
          return { pending_id: 'abc123', template: 'vm-lxc-qr', count: 2, warnings: [] };
        },
      }),
    );
    const { user } = renderPage();
    const load = await screen.findByRole('button', { name: 'Laden' });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(load);
    await screen.findByRole('table', { name: 'Gäste' });

    const print = screen.getByRole('button', { name: 'Als Serie drucken' });
    expect(print).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: '111 webapp1 auswählen' }));
    await user.click(screen.getByRole('checkbox', { name: '102 frigate auswählen' }));
    await user.click(print);

    await waitFor(() => expect(sent).toEqual({ host: 'pmx10', vmids: [102, 111], links: true }));
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=vm-lxc-qr&import=abc123'),
    );
  });

  it('ohne QR-Schalter wird links false gesendet', async () => {
    let sent: unknown = null;
    mockApi(
      routes({
        'POST /api/v1/homelab/proxmox/table': ({ body }) => {
          sent = body;
          return { pending_id: 'p2', template: 'vm-lxc', count: 1, warnings: [] };
        },
      }),
    );
    const { user } = renderPage();
    const load = await screen.findByRole('button', { name: 'Laden' });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(load);
    await screen.findByRole('table', { name: 'Gäste' });
    await user.click(screen.getByRole('checkbox', { name: '120 win11-test auswählen' }));
    await user.click(screen.getByRole('switch', { name: 'QR mit Link (Kurz-Link bzw. Proxmox-Adresse)' }));
    await user.click(screen.getByRole('button', { name: 'Als Serie drucken' }));
    await waitFor(() => expect(sent).toEqual({ host: 'pmx10', vmids: [120], links: false }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=vm-lxc&import=p2'));
  });

  it('Fehler „Token fehlt“ zeigt Meldung und Hinweis', async () => {
    mockApi(
      routes({
        'POST /api/v1/homelab/proxmox/guests': () =>
          new MockResponse(424, {
            error: {
              kind: 'TokenMissing',
              message: 'Zugangsdaten: Token fehlt: Proxmox pmx10 (Datei C:\\Tokens\\.proxmox_tapesmith_token)',
              hint: 'Token als Datei C:\\Tokens\\.proxmox_tapesmith_token ablegen (eine Zeile, nur das Token)',
              exit_code: 1,
              details: null,
            },
          }),
      }),
    );
    const { user } = renderPage();
    const load = await screen.findByRole('button', { name: 'Laden' });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(load);
    expect(await screen.findByText(/Token fehlt: Proxmox pmx10/)).toBeInTheDocument();
    expect(screen.getByText(/ablegen \(eine Zeile, nur das Token\)/)).toBeInTheDocument();
    expect(screen.getByText(/proxmox-tapesmith-role\.sh auf dem Proxmox-Host/)).toBeInTheDocument();
  });

  it('ohne Hosts erscheint ein leerer Zustand', async () => {
    mockApi(routes({ 'GET /api/v1/homelab/proxmox/hosts': () => ({ hosts: [] }) }));
    renderPage();
    expect(await screen.findByText('Noch kein Proxmox-Host eingerichtet')).toBeInTheDocument();
  });
});
