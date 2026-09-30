/** Einmalige Rückfrage nach der automatischen Update-Prüfung in der Hülle. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import type { UpdateStatus } from '../../api/update';
import { makeUpdateStatus } from '../../pages/Einstellungen/testFixtures';
import { fixtures, LocationProbe, mockApi, renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';

function consentApi(initial: Partial<UpdateStatus>, opts?: { failPost?: boolean }) {
  let current = makeUpdateStatus({ enabled: false, ...initial });
  return mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
      'GET /api/v1/drafts': () => ({ drafts: [], own: [], orphaned: [] }),
      'POST /api/v1/drafts/heartbeat': () => ({ alive_s: 90 }),
      'GET /api/v1/update/status': () => current,
      'POST /api/v1/update/consent': (req) => {
        if (opts?.failPost) throw new Error('Speichern fehlgeschlagen');
        const body = req.body as { enabled: boolean };
        current = { ...current, enabled: body.enabled, consent_needed: false };
        return current;
      },
    },
    { quiet: true },
  );
}

describe('UpdateConsentBanner', () => {
  it('fragt einmal und speichert „Ja, automatisch suchen“', async () => {
    const api = consentApi({ consent_needed: true });
    const { user, container } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    expect(await screen.findByText('Automatisch nach Updates suchen?')).toBeInTheDocument();
    expect(screen.getByText(/api\.github\.com/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
    await user.click(screen.getByRole('button', { name: 'Ja, automatisch suchen' }));
    await waitFor(() => expect(screen.queryByTestId('update-consent')).toBeNull());
    const post = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/update/consent');
    expect(post?.body).toEqual({ enabled: true });
  });

  it('„Nein, nur auf Wunsch“ speichert die Ablehnung', async () => {
    const api = consentApi({ consent_needed: true });
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await user.click(await screen.findByRole('button', { name: 'Nein, nur auf Wunsch' }));
    await waitFor(() => expect(screen.queryByTestId('update-consent')).toBeNull());
    const post = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/update/consent');
    expect(post?.body).toEqual({ enabled: false });
  });

  it('ohne offene Rückfrage kein Hinweis', async () => {
    const api = consentApi({ consent_needed: false });
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/update/status')).toBe(true));
    expect(screen.queryByTestId('update-consent')).toBeNull();
  });

  it('Fehler beim Speichern bleibt sichtbar, der Hinweis bleibt stehen', async () => {
    consentApi({ consent_needed: true }, { failPost: true });
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await user.click(await screen.findByRole('button', { name: 'Ja, automatisch suchen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Die Antwort konnte nicht gespeichert werden.');
    expect(screen.getByTestId('update-consent')).toBeInTheDocument();
  });
});
