/** Barrierefreiheit und Tastatur der Seite Proxmox: axe in de/en, Tastatur. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import ProxmoxPage from './index';
import type { GuestsJson, PveHostsJson } from './types';

const HOSTS: PveHostsJson = {
  hosts: [
    { name: 'pmx10', url: 'https://192.0.2.60:8006', verify_tls: false, token_set: true, token_describe: 'Datei C:\\Tokens\\.proxmox_tapesmith_token' },
  ],
};

const GUESTS: GuestsJson = {
  host: 'pmx10',
  nodes: [{ host: 'pmx10', node: 'pmx10', status: 'online', ip: '192.0.2.60' }],
  guests: [
    {
      host: 'pmx10', node: 'pmx10', vmid: 111, kind: 'qemu', name: 'webapp1', status: 'running', tags: ['ai'],
      ips: ['192.0.2.39'], ip_note: '', passthrough: [], ip_kurz: '.39',
    },
  ],
  warnings: [],
};

const LOAD = { de: 'Laden', en: 'Load' } as const;

describe.each(['de', 'en'] as Language[])('Proxmox a11y (%s)', (language) => {
  it('Grundzustand ohne axe-Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/proxmox/hosts': () => HOSTS, 'POST /api/v1/homelab/proxmox/guests': () => GUESTS });
    const { container, user } = renderWithProviders(<ProxmoxPage />, { language, route: '/homelab/proxmox' });
    const load = await screen.findByRole('button', { name: LOAD[language] });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(load);
    await screen.findByRole('table', { name: language === 'de' ? 'Gäste' : 'Guests' });
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (keine Hosts) ohne axe-Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/proxmox/hosts': () => ({ hosts: [] }) });
    const { container } = renderWithProviders(<ProxmoxPage />, { language, route: '/homelab/proxmox' });
    await screen.findByRole('heading', { level: 2 });
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand (Token fehlt) ohne axe-Befund', async () => {
    mockApi({
      'GET /api/v1/homelab/proxmox/hosts': () => HOSTS,
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
    });
    const { container, user } = renderWithProviders(<ProxmoxPage />, { language, route: '/homelab/proxmox' });
    const load = await screen.findByRole('button', { name: LOAD[language] });
    await waitFor(() => expect(load).toBeEnabled());
    await user.click(load);
    await screen.findByText(/Token fehlt: Proxmox pmx10/);
    await expectNoA11yViolations(container);
  });
});

describe('Proxmox Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi({ 'GET /api/v1/homelab/proxmox/hosts': () => HOSTS });
    renderWithProviders(<ProxmoxPage />, { language: 'en', route: '/homelab/proxmox' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Proxmox' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load' })).toBeInTheDocument();
  });
});

describe('Proxmox Tastatur', () => {
  it('Hauptaktion (Laden) per Tastatur erreichbar und auslösbar', async () => {
    mockApi({ 'GET /api/v1/homelab/proxmox/hosts': () => HOSTS, 'POST /api/v1/homelab/proxmox/guests': () => GUESTS });
    const { user } = renderWithProviders(<ProxmoxPage />, { route: '/homelab/proxmox' });
    const load = await screen.findByRole('button', { name: 'Laden' });
    await waitFor(() => expect(load).toBeEnabled());
    load.focus();
    expect(load).toHaveFocus();
    await user.keyboard('{Enter}');
    await screen.findByRole('table', { name: 'Gäste' });
  });
});
