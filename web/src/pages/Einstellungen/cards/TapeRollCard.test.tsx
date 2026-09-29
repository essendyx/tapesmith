import { describe, expect, it } from 'vitest';
import { waitFor, within } from '@testing-library/react';
import { findDialog, mockApi, renderWithProviders } from '../../../test/utils';
import { baseSettingsRoutes } from '../testFixtures';
import EinstellungenPage from '../index';
import type { TapeInfo } from '../../../api/types';

const tapeWeiss: TapeInfo = {
  id: 'w12',
  name: 'Weiß 12 mm',
  background: '#ffffff',
  ink: '#000000',
  material: 'Papier',
  transparent: false,
  dark: false,
  code_mode: 'normal',
  density: null,
  current: true,
};

const tapeSchwarz: TapeInfo = {
  ...tapeWeiss,
  id: 'b12',
  name: 'Weiß auf Schwarz',
  background: '#000000',
  ink: '#ffffff',
  dark: true,
  current: false,
};

describe('Karte Band und Rolle', () => {
  it('Verbrauchsbalken der laufenden Rolle hat einen zugänglichen Namen (axe im echten Browser)', async () => {
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/tapes': () => ({ tapes: [tapeWeiss], current: 'w12' }),
        'GET /api/v1/rolls': () => ({
          current: {
            tape_id: 'w12', tape_name: 'Weiß 12 mm', started: '2026-09-01T10:00:00', length_mm: 4000, used_mm: 1400,
            remaining_mm: 2600, spread_mm: null, jobs: 12, factor: 1, summary: 'Weiß 12 mm: 1,4 m von 4 m',
          },
          all: [],
        }),
      }),
    );
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });
    const card = document.getElementById('band') as HTMLElement;
    expect(await within(card).findByRole('progressbar', { name: 'Verbrauch der laufenden Rolle' })).toBeInTheDocument();
  });

  it('Klick auf „Weiß auf Schwarz“ sendet PUT /tapes/current', async () => {
    let sentId: string | null = null;
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/tapes': () => ({ tapes: [tapeWeiss, tapeSchwarz], current: 'w12' }),
        'PUT /api/v1/tapes/current': ({ body }) => {
          sentId = (body as { id: string }).id;
          return { tapes: [tapeWeiss, { ...tapeSchwarz, current: true }], current: 'b12' };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const card = document.getElementById('band') as HTMLElement;
    await user.click(await within(card).findByText('Weiß auf Schwarz'));

    await waitFor(() => expect(sentId).toBe('b12'));
  });

  it('„Neue Rolle“ sendet POST /rolls/new mit length_mm: 4000', async () => {
    let sentBody: unknown = null;
    mockApi(
      baseSettingsRoutes({
        'GET /api/v1/tapes': () => ({ tapes: [tapeWeiss], current: 'w12' }),
        'POST /api/v1/rolls/new': ({ body }) => {
          sentBody = body;
          return { current: null, all: [] };
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const card = document.getElementById('band') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Neue Rolle' }));
    const dialog = await findDialog('Neue Rolle');
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen', hidden: true }));

    await waitFor(() => expect(sentBody).toEqual({ length_mm: 4000 }));
  });
});
