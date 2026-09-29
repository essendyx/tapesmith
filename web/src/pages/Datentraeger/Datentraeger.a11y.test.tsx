import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { DriveJson, SshHostJson } from '../../api/types';
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

describe('Datentraeger: Barrierefreiheit', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Laufwerke gefüllt ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/drives': () => ({ drives: [drive] }) });
      const { container } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger', language });
      await screen.findByText((text) => text.includes('64 GB · exFAT'));
      await expectNoA11yViolations(container);
    });

    it(`Laufwerke leer ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/drives': () => ({ drives: [] }) });
      const { container } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger', language });
      await screen.findByRole('status');
      await expectNoA11yViolations(container);
    });

    it(`SSH-Fehler ohne axe-Befund (${language})`, async () => {
      mockApi({
        'GET /api/v1/ssh/hosts': () => ({ hosts: [host] }),
        'POST /api/v1/ssh/scan': () =>
          new MockResponse(502, { error: { kind: 'SSH', message: 'x', hint: 'y', exit_code: 1, details: null } }),
      });
      const { user, container } = renderWithProviders(<DatentraegerPage />, { route: '/datentraeger?tab=ssh', language });
      await screen.findByText('pmx10');
      await user.click(screen.getByRole('button', { name: language === 'de' ? 'Scannen' : 'Scan' }));
      await screen.findByText('x');
      await expectNoA11yViolations(container);
    });
  }

  it('Tastatur: „Aktualisieren" per Tab erreichbar und per Enter auslösbar', async () => {
    const api = mockApi({ 'GET /api/v1/drives': () => ({ drives: [drive] }) });
    renderWithProviders(<DatentraegerPage />, { route: '/datentraeger' });
    await screen.findByText((text) => text.includes('64 GB · exFAT'));
    const button = screen.getByRole('button', { name: 'Aktualisieren' });
    button.focus();
    expect(button).toHaveFocus();
    const userEvent = (await import('@testing-library/user-event')).default;
    await userEvent.setup().keyboard('{Enter}');
    await waitFor(() => expect(api.calls.filter((c) => c.path === '/api/v1/drives').length).toBeGreaterThan(1));
  });
});
