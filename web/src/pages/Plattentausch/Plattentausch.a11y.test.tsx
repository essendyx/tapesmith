/** Barrierefreiheit und Tastatur der Seite Plattentausch: axe in de/en, Tastatur. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { fixtures, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { SshHostJson } from '../../api/types';
import type { Language } from '../../i18n';
import type { ReplacePlanJson, ZfsOverviewJson } from './types';
import PlattentauschPage from '.';

const host: SshHostJson = { name: 'pmx10', host: '192.0.2.60', user: 'root', port: 22, key: '%USERPROFILE%\\.ssh\\id_ed25519_homelab' };

const overview: ZfsOverviewJson = {
  host: 'pmx10',
  scanned_at: '2026-09-28T09:00:00',
  previous_scanned_at: null,
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

const SCAN = { de: 'Scannen', en: 'Scan' } as const;

describe.each(['de', 'en'] as Language[])('Plattentausch a11y (%s)', (language) => {
  it('Grundzustand ohne axe-Befund', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => overview,
      'POST /api/v1/homelab/zfs/plan': () => plan,
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
    });
    const { container, user } = renderWithProviders(<PlattentauschPage />, { language, route: '/homelab/plattentausch' });
    await user.click(await screen.findByRole('button', { name: SCAN[language] }));
    await screen.findByText('rpool');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand ohne axe-Befund', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => emptyOverview,
    });
    const { container, user } = renderWithProviders(<PlattentauschPage />, { language, route: '/homelab/plattentausch' });
    await user.click(await screen.findByRole('button', { name: SCAN[language] }));
    await screen.findByRole('heading', { level: 2, name: language === 'de' ? 'Keine defekten Geräte, alle Pools ONLINE' : 'No failed drives, all pools ONLINE' });
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand ohne axe-Befund', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () =>
        new MockResponse(502, { error: { kind: 'SSH', message: 'Host-Schlüssel nicht bekannt', hint: 'Host-Schlüssel bestätigen und erneut versuchen', exit_code: 1, details: null } }),
    });
    const { container, user } = renderWithProviders(<PlattentauschPage />, { language, route: '/homelab/plattentausch' });
    await user.click(await screen.findByRole('button', { name: SCAN[language] }));
    await screen.findByText('Host-Schlüssel nicht bekannt');
    await expectNoA11yViolations(container);
  });
});

describe('Plattentausch Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi({ 'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }) });
    renderWithProviders(<PlattentauschPage />, { language: 'en', route: '/homelab/plattentausch' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Swap drive' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Scan' })).toBeInTheDocument();
  });
});

describe('Plattentausch Tastatur', () => {
  it('Hauptaktion (Scannen) per Tastatur erreichbar und auslösbar', async () => {
    mockApi({
      'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
      'POST /api/v1/homelab/zfs/scan': () => overview,
    });
    const { user } = renderWithProviders(<PlattentauschPage />, { route: '/homelab/plattentausch' });
    const scanButton = await screen.findByRole('button', { name: 'Scannen' });
    scanButton.focus();
    expect(scanButton).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByText('rpool')).toBeInTheDocument());
  });
});
