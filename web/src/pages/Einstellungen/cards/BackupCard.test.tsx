import { describe, expect, it } from 'vitest';
import { within } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../../test/utils';
import { baseSettingsRoutes } from '../testFixtures';
import EinstellungenPage from '../index';

describe('Karte Sicherung', () => {
  it('„Wiederherstellen…“ sendet den Probelauf und zeigt den Konsolenhinweis', async () => {
    let sentBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/backups': () => ({
          dir: 'C:/Sicherung',
          backups: [{ name: '2026-09-27_1200', path: 'C:/Sicherung/2026-09-27_1200.zip', created: '2026-09-27T12:00:00', size_bytes: 2048 }],
        }),
        'POST /api/v1/backups/restore': ({ body }) => {
          sentBody = body;
          return { lines: ['config.json wird ersetzt', 'templates/ wird ersetzt'] };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = document.getElementById('sicherung') as HTMLElement;

    await user.click(await within(card).findByRole('button', { name: 'Wiederherstellen…' }));

    expect(sentBody).toEqual({ name: '2026-09-27_1200', dry_run: true });
    expect(await within(card).findByText(/tapesmith daemon stop/)).toBeInTheDocument();
    expect(within(card).getByText(/config.json wird ersetzt/)).toBeInTheDocument();
  });
});
