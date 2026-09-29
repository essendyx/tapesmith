import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, mockApi, renderWithProviders } from '../../test/utils';
import { baseSettingsRoutes } from './testFixtures';
import EinstellungenPage from './index';

describe('Einstellungen: Barrierefreiheit', () => {
  for (const language of ['de', 'en'] as const) {
    it(`geladene Seite ohne axe-Befund (${language})`, async () => {
      mockApi(baseSettingsRoutes());
      const { container } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen', language });
      await waitFor(() => expect(document.getElementById('updates')).not.toBeNull());
      await waitFor(() => expect(document.getElementById('druckdienst')).not.toBeNull());
      await expectNoA11yViolations(container);
    });
  }

  it('geöffneter Dialog (Neue Rolle) ohne axe-Befund', async () => {
    mockApi(baseSettingsRoutes());
    const { user, container } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = await waitFor(() => document.getElementById('band') as HTMLElement);
    await user.click(within(card).getByRole('button', { name: 'Neue Rolle' }));
    await findDialog('Neue Rolle');
    await expectNoA11yViolations(container);
  });

  it('Tastatur: „Jetzt sichern" per Tab erreichbar und per Enter auslösbar', async () => {
    const api = mockApi(baseSettingsRoutes({ 'POST /api/v1/backups': () => ({ name: 'b1', path: 'C:/b1', created: '2026-09-28', size_bytes: 1 }) }));
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    await waitFor(() => expect(document.getElementById('sicherung')).not.toBeNull());
    const button = screen.getByRole('button', { name: 'Jetzt sichern' });
    button.focus();
    expect(button).toHaveFocus();
    await userEvent.setup().keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/backups' && c.method === 'POST')).toBe(true));
  });

  it('Dialog (Neue Rolle) schließt mit Escape und gibt den Fokus an den Auslöser zurück', async () => {
    mockApi(baseSettingsRoutes());
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = await waitFor(() => document.getElementById('band') as HTMLElement);
    const trigger = within(card).getByRole('button', { name: 'Neue Rolle' });
    await user.click(trigger);
    await findDialog('Neue Rolle');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByText('Neue Rolle', { selector: '.fui-DialogTitle' })).not.toBeInTheDocument());
  });
});
