import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { fixtures, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { SshHostJson } from '../../api/types';
import type { ReplacePlanJson, ZfsOverviewJson } from './types';
import PlattentauschPage from '.';

const host: SshHostJson = { name: 'pmx10', host: '192.0.2.60', user: 'root', port: 22, key: '%USERPROFILE%\\.ssh\\id_ed25519_homelab' };

const overview: ZfsOverviewJson = {
  host: 'pmx10',
  scanned_at: '2026-09-28T09:00:00',
  previous_scanned_at: '2026-09-20T08:00:00',
  disks: [],
  pools: [],
  problems: [
    {
      pool: 'rpool', vdev: 'mirror-0', name: '/dev/disk/by-id/ata-Samsung-123-part3', state: 'FAULTED',
      read: '3', write: '120', cksum: '0', note: 'too many errors', was_path: null,
      by_id: 'ata-Samsung-123', partition: 'part3', device: 'sda',
    },
  ],
  candidates: [
    {
      disk: { host: 'pmx10', device: 'sdc', model: 'Samsung SSD 870 EVO', serial: 'S5Y1NX0R999999', size: '931.5G', tran: 'sata', wwn: '', by_id: 'ata-Samsung-999999', pool: null, vdev: null },
      reason: 'in keinem Pool',
    },
  ],
};

const emptyOverview: ZfsOverviewJson = { ...overview, problems: [], candidates: [] };

const plan: ReplacePlanJson = {
  host: 'pmx10', pool: 'rpool', old: overview.problems[0]!, old_serial: 'S5Y1NX0R123456', old_model: 'Samsung SSD 870 EVO 1TB',
  new: overview.candidates[0]!.disk, command: 'zpool replace rpool /dev/disk/by-id/ata-Samsung-123 /dev/disk/by-id/ata-Samsung-999999',
  hints: ['Befehl erst nach Prüfung von Pool, alter und neuer Platte ausführen, die App führt nichts aus.'],
  changelog_md: '### Platte getauscht: pmx10 · Pool rpool\n- Links: [[Hosts/pmx10]]',
  old_label: { template: 'platte-defekt', values: { host: 'pmx10', slot: 'SSD-1', sn: 'S5Y1NX0R123456', datum: '28.09.2026', grund: 'faulted' } },
  new_label: { template: 'datentraeger', values: { host: 'pmx10', slot: 'SSD-1', sn: 'S5Y1NX0R999999' } },
};

async function scanAndSelect(user: ReturnType<typeof renderWithProviders>['user']) {
  await screen.findByRole('button', { name: 'Scannen' });
  await user.click(screen.getByRole('button', { name: 'Scannen' }));
  await screen.findByText('rpool');
  await user.click(screen.getByRole('radio', { name: /Defektes Gerät/ }));
  await user.click(screen.getByRole('radio', { name: /sdc/ }));
  await user.type(screen.getByLabelText('Slot'), 'SSD-1');
}

describe('PlattentauschPage', () => {
  it('Scan zeigt defektes Gerät und Kandidaten; Plan erstellen sendet den Antrag und zeigt den Befehl', async () => {
    const api = mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => overview,
      'POST /api/v1/homelab/zfs/plan': () => plan,
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { user } = renderWithProviders(<PlattentauschPage />, { route: '/homelab/plattentausch' });
    await scanAndSelect(user);

    await user.click(screen.getByRole('button', { name: 'Plan erstellen' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/homelab/zfs/plan')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/homelab/zfs/plan');
    expect(call?.body).toMatchObject({ host: 'pmx10', old: overview.problems[0]!.name, new_device: 'sdc', slot: 'SSD-1' });

    expect(await screen.findByText(plan.command)).toBeInTheDocument();
  });

  it('Druck „Label alte Platte" sendet labels/print mit template platte-defekt und den Werten aus dem Plan', async () => {
    const api = mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => overview,
      'POST /api/v1/homelab/zfs/plan': () => plan,
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ title: 'defekt' }),
    });
    const { user } = renderWithProviders(<PlattentauschPage />, { route: '/homelab/plattentausch' });
    await scanAndSelect(user);
    await user.click(screen.getByRole('button', { name: 'Plan erstellen' }));
    await screen.findByText(plan.command);

    await user.click(screen.getByRole('button', { name: 'Label alte Platte drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { source: { kind: string; template: string; values: Record<string, string> } };
    expect(body.source.kind).toBe('template');
    expect(body.source.template).toBe('platte-defekt');
    expect(body.source.values.datum).toBe('28.09.2026');
  });

  it('Druck „Label neue Platte" sendet labels/print mit template datentraeger', async () => {
    const api = mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => overview,
      'POST /api/v1/homelab/zfs/plan': () => plan,
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ title: 'neu' }),
    });
    const { user } = renderWithProviders(<PlattentauschPage />, { route: '/homelab/plattentausch' });
    await scanAndSelect(user);
    await user.click(screen.getByRole('button', { name: 'Plan erstellen' }));
    await screen.findByText(plan.command);

    await user.click(screen.getByRole('button', { name: 'Label neue Platte drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = call?.body as { source: { kind: string; template: string } };
    expect(body.source.template).toBe('datentraeger');
  });

  it('Ohne Probleme erscheint der Leerzustand', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => emptyOverview,
    });
    const { user } = renderWithProviders(<PlattentauschPage />, { route: '/homelab/plattentausch' });
    await screen.findByRole('button', { name: 'Scannen' });
    await user.click(screen.getByRole('button', { name: 'Scannen' }));
    expect(await screen.findByText('Keine defekten Geräte, alle Pools ONLINE')).toBeInTheDocument();
  });

  it('Scan-Fehler (502 mit kind: "SSH") zeigt Meldung', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () =>
        new MockResponse(502, { error: { kind: 'SSH', message: 'Host-Schlüssel nicht bekannt', hint: 'Host-Schlüssel bestätigen und erneut versuchen', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<PlattentauschPage />, { route: '/homelab/plattentausch' });
    await screen.findByRole('button', { name: 'Scannen' });
    await user.click(screen.getByRole('button', { name: 'Scannen' }));
    expect(await screen.findByText('Host-Schlüssel nicht bekannt')).toBeInTheDocument();
    expect(screen.getByText('Host-Schlüssel bestätigen und erneut versuchen')).toBeInTheDocument();
  });
});
